#!/usr/bin/env bash
# Etapa 1 - Verificacion del entorno para el proyecto STP vs MPLS
#
# Revisa que el equipo tenga todo lo necesario y hace una prueba minima de MPLS
# con dos namespaces de red, sin Mininet, para aislar problemas del kernel.
#
# Uso:  sudo bash verificar_entorno.sh

set -u
FALLAS=0
AVISOS=0
ok()    { echo "  [OK]    $*"; }
falla() { echo "  [FALLA] $*"; FALLAS=$((FALLAS + 1)); }
aviso() { echo "  [AVISO] $*"; AVISOS=$((AVISOS + 1)); }
info()  { echo "          $*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecuta con sudo:  sudo bash $0"
    exit 1
fi

# ---------------------------------------------------------------------------
echo "== 1. Sistema"
if [ -r /etc/os-release ]; then
    . /etc/os-release
    ok "${PRETTY_NAME:-Linux}, kernel $(uname -r), $(uname -m)"
fi
if grep -qi microsoft /proc/version 2>/dev/null; then
    aviso "Esto es WSL. Si la seccion 4 falla, usen una VM con Ubuntu (ver README)."
fi
if command -v systemd-detect-virt >/dev/null 2>&1; then
    info "virtualizacion: $(systemd-detect-virt 2>/dev/null || echo ninguna)"
fi

# ---------------------------------------------------------------------------
echo "== 2. Herramientas"
for b in mn mnexec ip tcpdump iperf3 ethtool ping python3 sysctl modprobe; do
    if command -v "$b" >/dev/null 2>&1; then
        ok "$b"
    else
        falla "$b no esta instalado"
    fi
done
if python3 -c 'import mininet.net' 2>/dev/null; then
    ok "python3 importa mininet ($(mn --version 2>&1 | tail -1))"
else
    falla "python3 no encuentra el paquete mininet (sudo apt install mininet)"
fi
if command -v tshark >/dev/null 2>&1 || command -v wireshark >/dev/null 2>&1; then
    ok "Wireshark/tshark"
else
    aviso "Wireshark no esta instalado (sudo apt install wireshark). Se usa para ver las capturas."
fi

# ---------------------------------------------------------------------------
echo "== 3. Open vSwitch y Mininet (lo usara el escenario STP)"
if command -v ovs-vsctl >/dev/null 2>&1 && ovs-vsctl show >/dev/null 2>&1; then
    ok "Open vSwitch esta corriendo ($(ovs-vsctl --version | head -1))"
    if timeout 60 mn --switch ovsbr --controller none --test pingall 2>&1 \
            | grep -q "Results: 0% dropped"; then
        ok "Mininet: 'mn --test pingall' sin perdidas"
    else
        falla "Mininet no paso 'mn --switch ovsbr --controller none --test pingall'"
        info "Prueben 'sudo mn -c' y vuelvan a correr este script"
    fi
    mn -c >/dev/null 2>&1
else
    falla "Open vSwitch no responde"
    info "sudo apt install openvswitch-switch && sudo systemctl enable --now openvswitch-switch"
fi

# ---------------------------------------------------------------------------
echo "== 4. MPLS en el kernel"
MPLS_OK=1
for m in mpls_router mpls_iptunnel; do
    if modprobe "$m" 2>/dev/null; then
        ok "modulo $m cargado"
    else
        falla "no se pudo cargar el modulo $m"
        info "Prueben: sudo apt install linux-modules-extra-\$(uname -r)  y repitan"
        MPLS_OK=0
    fi
done
if modprobe mpls_gso 2>/dev/null; then
    ok "modulo mpls_gso cargado"
else
    aviso "mpls_gso no esta disponible (no es critico: el script desactiva GSO)"
fi
if [ -d /proc/sys/net/mpls ]; then
    ok "/proc/sys/net/mpls existe"
    info "valor por defecto de net.mpls.platform_labels: $(sysctl -n net.mpls.platform_labels)"
    info "(0 = el kernel no reconoce ninguna etiqueta; hay que subirlo en cada router)"
else
    falla "/proc/sys/net/mpls no existe: este kernel no tiene MPLS"
    MPLS_OK=0
fi
if [ "$MPLS_OK" -eq 1 ]; then
    if ip -f mpls route show >/dev/null 2>&1; then
        ok "iproute2 entiende rutas MPLS ($(ip -V))"
    else
        falla "iproute2 no acepta 'ip -f mpls route' (actualicen iproute2)"
        MPLS_OK=0
    fi
fi

# ---------------------------------------------------------------------------
echo "== 5. Prueba minima de MPLS con dos namespaces (sin Mininet)"
#   [ns mplsA] vA 10.255.0.1/30 ---- 10.255.0.2/30 vB [ns mplsB]  lo: 10.255.1.1/32
#   A inserta la etiqueta 50 hacia 10.255.1.1; B la quita y entrega el paquete.
if [ "$MPLS_OK" -eq 1 ]; then
    limpiar() {
        ip netns del mplsA 2>/dev/null
        ip netns del mplsB 2>/dev/null
        ip link del vA 2>/dev/null
    }
    trap limpiar EXIT
    limpiar
    ip netns add mplsA
    ip netns add mplsB
    ip link add vA type veth peer name vB
    ip link set vA netns mplsA
    ip link set vB netns mplsB
    for ns in mplsA mplsB; do
        ip -n "$ns" link set lo up
        ip netns exec "$ns" sysctl -qw net.ipv4.conf.all.rp_filter=0 \
            net.ipv4.conf.default.rp_filter=0
    done
    ip -n mplsA addr add 10.255.0.1/30 dev vA
    ip -n mplsA link set vA up
    ip -n mplsB addr add 10.255.0.2/30 dev vB
    ip -n mplsB addr add 10.255.1.1/32 dev lo
    ip -n mplsB link set vB up
    ip netns exec mplsB sysctl -qw net.ipv4.conf.vB.rp_filter=0

    # 5a. Con platform_labels=0 (valor por defecto) no se puede crear la ruta
    if ip -n mplsB -f mpls route add 50 dev lo 2>/dev/null; then
        aviso "se pudo crear una ruta MPLS con platform_labels=0 (inesperado)"
        ip -n mplsB -f mpls route del 50 2>/dev/null
    else
        ok "con platform_labels=0 el kernel rechaza la ruta de la etiqueta 50"
    fi

    ip netns exec mplsB sysctl -qw net.mpls.platform_labels=100
    ip -n mplsB -f mpls route add 50 dev lo
    ip -n mplsA route add 10.255.1.1/32 encap mpls 50 via 10.255.0.2 dev vA

    # 5b. Con conf/vB/input=0 (valor por defecto) B descarta los paquetes
    if ip netns exec mplsA ping -c 2 -i 0.2 -W 1 10.255.1.1 >/dev/null 2>&1; then
        aviso "el ping paso con input=0 (inesperado)"
    else
        ok "con net.mpls.conf.vB.input=0 los paquetes etiquetados se descartan"
    fi

    # 5c. Con input=1, push en A y pop en B
    ip netns exec mplsB sysctl -qw net.mpls.conf.vB.input=1
    if ip netns exec mplsA ping -c 3 -i 0.2 -W 1 10.255.1.1 >/dev/null 2>&1; then
        ok "push en A y pop en B funcionan: ping a 10.255.1.1 por la etiqueta 50"
        info "$(ip -n mplsA route show 10.255.1.1)"
        info "$(ip -n mplsB -f mpls route show)"
    else
        falla "el ping por MPLS no paso aun con platform_labels e input configurados"
        MPLS_OK=0
    fi
else
    aviso "se omite: falta soporte MPLS (seccion 4)"
fi

# ---------------------------------------------------------------------------
echo
if [ "$FALLAS" -eq 0 ]; then
    echo "Resultado: todo listo ($AVISOS aviso(s)). Sigan con: sudo python3 validar_mpls.py"
    exit 0
else
    echo "Resultado: $FALLAS falla(s) y $AVISOS aviso(s). Revisen la seccion 'Problemas frecuentes' del README."
    exit 1
fi
