#!/usr/bin/env python3
"""
Etapa 1 - Validacion del entorno: Mininet + MPLS del kernel de Linux
Proyecto de Redes: STP vs MPLS (A. Lanchimba, E. Puga)

Monta la topologia base con routers Linux y comprueba, en orden:

  Paso A. Conectividad de un camino IP sin etiquetas (H1 -> R1 -> R2 -> R4 -> H2).
  Paso B. Insercion (R1), intercambio (R2) y eliminacion (R4) de etiquetas en el
          LSP-A. Antes muestra que los valores por defecto del kernel lo impiden:
          platform_labels=0 rechaza las rutas y conf/<intf>/input=0 descarta paquetes.
  Paso C. Los dos LSP a la vez. R1 separa los flujos por direccion de destino:
          10.0.2.11 -> LSP-A (R2) y 10.0.2.12 -> LSP-B (R3).

Cada paso es acumulativo (C incluye A y B). Al final deja:
  resultados/etapa1_resumen.json   resultado de cada prueba (PASA / FALLA)
  resultados/etapa1_bitacora.txt   cada comando ejecutado y su salida
  capturas/*.pcap                  capturas para abrir en Wireshark

Uso:
  sudo python3 validar_mpls.py              # pasos A, B y C
  sudo python3 validar_mpls.py --hasta A    # solo el paso A (no requiere MPLS)
  sudo python3 validar_mpls.py --cli        # abre la CLI de Mininet al terminar
  sudo python3 validar_mpls.py --sin-iperf  # omite la prueba corta con iperf3
"""

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from subprocess import DEVNULL, PIPE

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import Node

# ---------------------------------------------------------------------------
# Parametros de la topologia base (los mismos se usaran en el escenario STP)
# ---------------------------------------------------------------------------

BW_NUCLEO = 10      # Mbps en los cuatro enlaces del nucleo
BW_ACCESO = 100     # Mbps en H1-R1 y R4-H2 (> 20 Mbps, para que no limiten)
MTU_NUCLEO = 1600   # el nucleo lleva 4 bytes extra por etiqueta MPLS

H2_A = '10.0.2.11'  # destino del flujo 1 -> LSP-A (por R2)
H2_B = '10.0.2.12'  # destino del flujo 2 -> LSP-B (por R3)

# (nodo1, intf1, ip1, nodo2, intf2, ip2, ancho de banda, es_nucleo)
# El orden importa: la primera interfaz de cada nodo es su interfaz por defecto.
ENLACES = [
    ('h1', 'h1-eth0', '10.0.1.10/24', 'r1', 'r1-eth0', '10.0.1.1/24', BW_ACCESO, False),
    ('r1', 'r1-eth1', '10.0.12.1/24', 'r2', 'r2-eth0', '10.0.12.2/24', BW_NUCLEO, True),
    ('r1', 'r1-eth2', '10.0.13.1/24', 'r3', 'r3-eth0', '10.0.13.3/24', BW_NUCLEO, True),
    ('r2', 'r2-eth1', '10.0.24.2/24', 'r4', 'r4-eth0', '10.0.24.4/24', BW_NUCLEO, True),
    ('r3', 'r3-eth1', '10.0.34.3/24', 'r4', 'r4-eth1', '10.0.34.4/24', BW_NUCLEO, True),
    ('r4', 'r4-eth2', '10.0.2.1/24', 'h2', 'h2-eth0', H2_A + '/24', BW_ACCESO, False),
]
ROUTERS = ('r1', 'r2', 'r3', 'r4')

# Rutas IP del paso A. La vuelta (H2 -> H1) siempre va por IP normal via R2.
RUTAS_IP = {
    'r1': ['10.0.2.0/24 via 10.0.12.2'],
    'r2': ['10.0.1.0/24 via 10.0.12.1', '10.0.2.0/24 via 10.0.24.4'],
    'r3': ['10.0.1.0/24 via 10.0.13.1', '10.0.2.0/24 via 10.0.34.4'],
    'r4': ['10.0.1.0/24 via 10.0.24.2'],
}

# LSPs estaticos: R1 inserta, el router intermedio intercambia, R4 quita.
LSP = {
    'A': dict(destino=H2_A, push=100, swap=101, medio='r2',
              r1_sale='r1-eth1', r1_siguiente='10.0.12.2',
              medio_entra='r2-eth0', medio_sale='r2-eth1', medio_siguiente='10.0.24.4',
              r4_entra='r4-eth0'),
    'B': dict(destino=H2_B, push=200, swap=201, medio='r3',
              r1_sale='r1-eth2', r1_siguiente='10.0.13.3',
              medio_entra='r3-eth0', medio_sale='r3-eth1', medio_siguiente='10.0.34.4',
              r4_entra='r4-eth1'),
}
PLATFORM_LABELS = 1000  # tamano de la tabla de etiquetas (debe superar 201)

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_RESULTADOS = os.path.join(DIR_BASE, 'resultados')
DIR_CAPTURAS = os.path.join(DIR_BASE, 'capturas')

RESULTADOS = []
BITACORA = None


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

class LinuxRouter(Node):
    """Nodo con reenvio IP activado (cada router vive en su propio namespace)."""

    def config(self, **params):
        super().config(**params)
        self.cmd('sysctl -qw net.ipv4.ip_forward=1')

    def terminate(self):
        self.cmd('sysctl -qw net.ipv4.ip_forward=0')
        super().terminate()


def log(texto=''):
    print(texto, flush=True)
    if BITACORA:
        BITACORA.write(texto + '\n')
        BITACORA.flush()


def titulo(texto):
    log('\n' + '=' * 72)
    log(texto)
    log('=' * 72)


def ejecutar(nodo, comando, mostrar=True):
    """Ejecuta un comando dentro del nodo y lo deja en la bitacora."""
    salida = nodo.cmd(comando)
    if BITACORA:
        BITACORA.write('[%s] $ %s\n%s' % (nodo.name, comando, salida))
        if salida and not salida.endswith('\n'):
            BITACORA.write('\n')
        BITACORA.flush()
    if mostrar:
        print('  [%s] $ %s' % (nodo.name, comando), flush=True)
        for linea in salida.strip().splitlines():
            print('        ' + linea, flush=True)
    return salida


def registrar(id_prueba, descripcion, esperado, ok, detalle=''):
    RESULTADOS.append(dict(id=id_prueba, descripcion=descripcion, esperado=esperado,
                           resultado='PASA' if ok else 'FALLA', detalle=detalle.strip()))
    log('  >> [%s] %s: %s' % ('PASA ' if ok else 'FALLA', id_prueba, descripcion))
    if not ok and detalle:
        log('     detalle: ' + detalle.strip().replace('\n', '\n              '))


def ping(nodo, destino, n=3):
    salida = ejecutar(nodo, 'ping -c %d -i 0.2 -W 1 %s' % (n, destino), mostrar=False)
    m = re.search(r'(\d+(?:\.\d+)?)% packet loss', salida)
    perdida = float(m.group(1)) if m else 100.0
    log('  [%s] ping %s -> %.0f %% de perdida' % (nodo.name, destino, perdida))
    return perdida, salida


class Captura:
    """tcpdump dentro del namespace de un nodo, guardado en capturas/<nombre>.pcap"""

    def __init__(self, nodo, intf, nombre):
        self.nombre = nombre
        self.ruta = os.path.join(DIR_CAPTURAS, nombre + '.pcap')
        if os.path.exists(self.ruta):
            os.remove(self.ruta)
        # -Z root: tcpdump en Ubuntu baja privilegios antes de abrir el archivo.
        # --immediate-mode: entrega cada paquete al instante (sin esperar a llenar
        # el bufer), asi no se pierden los ultimos al detener la captura.
        self.proc = nodo.popen(['tcpdump', '-i', intf, '-nn', '-U', '--immediate-mode',
                                '-s', '256', '-Z', 'root', '-w', self.ruta],
                               stdout=DEVNULL, stderr=PIPE)

    def detener(self):
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        try:
            os.chmod(self.ruta, 0o644)
        except OSError:
            pass
        return leer_pcap(self.ruta)


def capturar(capturas):
    """Recibe capturas ya lanzadas y espera a que tcpdump este escuchando."""
    time.sleep(1.5)
    return capturas


def detener(capturas):
    time.sleep(1.0)
    return {c.nombre: c.detener() for c in capturas}


def leer_pcap(ruta):
    """Devuelve una lista de paquetes: {'etiquetas': [..], 'origen': ip, 'destino': ip}."""
    if not os.path.exists(ruta):
        return []
    salida = subprocess.run(['tcpdump', '-nn', '-r', ruta], stdout=PIPE, stderr=DEVNULL,
                            universal_newlines=True).stdout
    # tcpdump puede partir un paquete en varias lineas; las que empiezan con
    # espacio o tabulador son continuacion de la anterior
    lineas = []
    for linea in salida.splitlines():
        if linea[:1] in (' ', '\t') and lineas:
            lineas[-1] += ' ' + linea.strip()
        elif linea.strip():
            lineas.append(linea)
    paquetes = []
    for linea in lineas:
        ips = re.search(r'IP (\d+\.\d+\.\d+\.\d+)\S* > (\d+\.\d+\.\d+\.\d+)', linea)
        paquetes.append(dict(
            etiquetas=[int(x) for x in re.findall(r'label (\d+)', linea)],
            origen=ips.group(1) if ips else None,
            destino=ips.group(2) if ips else None))
    return paquetes


def contar(paquetes, etiqueta=None, destino=None, con_mpls=None):
    """Cuenta paquetes que cumplan los filtros dados."""
    n = 0
    for p in paquetes:
        if etiqueta is not None and etiqueta not in p['etiquetas']:
            continue
        if destino is not None and p['destino'] != destino:
            continue
        if con_mpls is True and not p['etiquetas']:
            continue
        if con_mpls is False and p['etiquetas']:
            continue
        n += 1
    return n


def resumen_captura(nombre, paquetes):
    etiquetas = sorted({e for p in paquetes for e in p['etiquetas']})
    destinos = sorted({p['destino'] for p in paquetes if p['destino']})
    log('  captura %-22s %3d paquetes | etiquetas vistas: %s | destinos IP: %s'
        % (nombre + '.pcap', len(paquetes), etiquetas or '-', destinos or '-'))


# ---------------------------------------------------------------------------
# Construccion de la red
# ---------------------------------------------------------------------------

def construir_red():
    net = Mininet(controller=None, link=TCLink, build=False)

    primera_ip = {}
    for n1, _, ip1, n2, _, ip2, _, _ in ENLACES:
        primera_ip.setdefault(n1, ip1)
        primera_ip.setdefault(n2, ip2)

    nodos = {
        'h1': net.addHost('h1', ip=primera_ip['h1'], defaultRoute='via 10.0.1.1'),
        'h2': net.addHost('h2', ip=primera_ip['h2'], defaultRoute='via 10.0.2.1'),
    }
    for r in ROUTERS:
        nodos[r] = net.addHost(r, cls=LinuxRouter, ip=primera_ip[r])

    for n1, i1, ip1, n2, i2, ip2, bw, _ in ENLACES:
        net.addLink(nodos[n1], nodos[n2], intfName1=i1, intfName2=i2,
                    params1={'ip': ip1}, params2={'ip': ip2}, bw=bw)

    net.start()
    preparar_nodos(net)
    return net


def preparar_nodos(net):
    titulo('Preparacion de los nodos')
    # MTU mayor en el nucleo: 1500 bytes de IP + 4 de etiqueta caben sin fragmentar
    for n1, i1, _, n2, i2, _, _, nucleo in ENLACES:
        if nucleo:
            ejecutar(net[n1], 'ip link set dev %s mtu %d' % (i1, MTU_NUCLEO), mostrar=False)
            ejecutar(net[n2], 'ip link set dev %s mtu %d' % (i2, MTU_NUCLEO), mostrar=False)
    log('  MTU %d en las interfaces del nucleo' % MTU_NUCLEO)

    for nodo in net.hosts:
        intfs = [i for i in nodo.intfNames() if i != 'lo']
        # Sin offloads: paquetes del tamano real (sin GSO de 64 KB) y checksums
        # correctos en Wireshark
        for intf in intfs:
            ejecutar(nodo, 'ethtool -K %s tx off tso off gso off gro off 2>/dev/null'
                     % intf, mostrar=False)
        # Sin filtro de ruta inversa: la vuelta de 10.0.2.12 entra a R1 por R2
        # aunque la ida salga por R3 (camino asimetrico)
        ajustes = ['net.ipv4.conf.all.rp_filter=0', 'net.ipv4.conf.default.rp_filter=0']
        ajustes += ['net.ipv4.conf.%s.rp_filter=0' % i for i in intfs]
        ejecutar(nodo, 'sysctl -qw ' + ' '.join(ajustes), mostrar=False)
    log('  offloads desactivados y rp_filter=0 en todos los nodos')

    ejecutar(net['h2'], 'ip addr add %s/24 dev h2-eth0' % H2_B)
    ejecutar(net['h2'], 'ip -br addr show dev h2-eth0')


# ---------------------------------------------------------------------------
# Pasos de la validacion
# ---------------------------------------------------------------------------

def paso_a(net):
    titulo('Paso A - Un camino IP sin etiquetas: H1 -> R1 -> R2 -> R4 -> H2')
    for r, rutas in RUTAS_IP.items():
        for ruta in rutas:
            ejecutar(net[r], 'ip route add ' + ruta)
    ejecutar(net['r1'], 'ip route get ' + H2_A)

    caps = capturar([Captura(net['r2'], 'r2-eth0', 'A_r2-eth0'),
                     Captura(net['r3'], 'r3-eth0', 'A_r3-eth0')])
    perdida_a, salida_a = ping(net['h1'], H2_A)
    perdida_b, salida_b = ping(net['h1'], H2_B)
    pk = detener(caps)
    for nombre, paquetes in pk.items():
        resumen_captura(nombre, paquetes)

    registrar('A1', 'H1 alcanza %s por IP' % H2_A, '0 % de perdida', perdida_a == 0, salida_a)
    registrar('A2', 'H1 alcanza %s por IP' % H2_B, '0 % de perdida', perdida_b == 0, salida_b)
    por_r2 = contar(pk['A_r2-eth0'], destino=H2_A)
    por_r3 = contar(pk['A_r3-eth0'], destino=H2_A) + contar(pk['A_r3-eth0'], destino=H2_B)
    registrar('A3', 'El trafico va por R2 y no por R3', 'paquetes en r2-eth0, ninguno en r3-eth0',
              por_r2 > 0 and por_r3 == 0, 'r2-eth0: %d, r3-eth0: %d' % (por_r2, por_r3))


def configurar_lsp(net, nombre):
    """Rutas de un LSP: push en R1, swap en el router intermedio, pop en R4."""
    l = LSP[nombre]
    ejecutar(net['r1'], 'ip route add %s/32 encap mpls %d via %s dev %s'
             % (l['destino'], l['push'], l['r1_siguiente'], l['r1_sale']))
    ejecutar(net[l['medio']], 'ip -f mpls route add %d as %d via inet %s dev %s'
             % (l['push'], l['swap'], l['medio_siguiente'], l['medio_sale']))
    ejecutar(net['r4'], 'ip -f mpls route add %d via inet %s dev r4-eth2'
             % (l['swap'], l['destino']))


def habilitar_entrada(net, nombre):
    l = LSP[nombre]
    ejecutar(net[l['medio']], 'sysctl -w net.mpls.conf.%s.input=1' % l['medio_entra'])
    ejecutar(net['r4'], 'sysctl -w net.mpls.conf.%s.input=1' % l['r4_entra'])


def paso_b(net):
    titulo('Paso B - Insercion, intercambio y eliminacion de etiquetas (LSP-A)')
    r2 = net['r2']

    log('\n-- B1. Valores por defecto: platform_labels=0')
    ejecutar(r2, 'sysctl net.mpls.platform_labels')
    salida = ejecutar(r2, 'ip -f mpls route add 100 as 101 via inet 10.0.24.4 dev r2-eth1')
    tabla = ejecutar(r2, 'ip -f mpls route show')
    rechazada = bool(salida.strip()) and not re.search(r'^100\b', tabla, re.M)
    registrar('B1', 'Con platform_labels=0 el kernel rechaza rutas de etiquetas',
              'error al crear la ruta', rechazada, salida + tabla)

    log('\n-- B2. platform_labels=%d en cada router (es un ajuste por namespace)'
        % PLATFORM_LABELS)
    for r in ROUTERS:
        ejecutar(net[r], 'sysctl -w net.mpls.platform_labels=%d' % PLATFORM_LABELS)
    configurar_lsp(net, 'A')
    ejecutar(r2, 'sysctl net.mpls.conf.r2-eth0.input')
    caps = capturar([Captura(r2, 'r2-eth0', 'B2_r2-eth0_input0')])
    perdida, salida = ping(net['h1'], H2_A, n=2)
    pk = detener(caps)
    resumen_captura('B2_r2-eth0_input0', pk['B2_r2-eth0_input0'])
    llegan = contar(pk['B2_r2-eth0_input0'], etiqueta=100, destino=H2_A)
    registrar('B2', 'Con conf/<intf>/input=0, R2 recibe la etiqueta 100 y descarta el paquete',
              '100 % de perdida y paquetes con etiqueta 100 en r2-eth0',
              perdida == 100 and llegan > 0,
              'perdida %.0f %%, paquetes con etiqueta 100: %d' % (perdida, llegan))

    log('\n-- B3. input=1 en las interfaces que reciben etiquetas del LSP-A')
    habilitar_entrada(net, 'A')
    ejecutar(net['r1'], 'ip route show')
    ejecutar(r2, 'ip -f mpls route show')
    ejecutar(net['r4'], 'ip -f mpls route show')
    caps = capturar([Captura(r2, 'r2-eth0', 'B3_r2-eth0'),
                     Captura(r2, 'r2-eth1', 'B3_r2-eth1'),
                     Captura(net['r4'], 'r4-eth2', 'B3_r4-eth2')])
    perdida, salida = ping(net['h1'], H2_A)
    pk = detener(caps)
    for nombre, paquetes in pk.items():
        resumen_captura(nombre, paquetes)

    registrar('B3', 'H1 alcanza %s a traves del LSP-A' % H2_A, '0 % de perdida',
              perdida == 0, salida)
    n = contar(pk['B3_r2-eth0'], etiqueta=100, destino=H2_A)
    registrar('B4', 'Push en R1: llegan a R2 con etiqueta 100', 'paquetes con etiqueta 100',
              n > 0, 'paquetes: %d' % n)
    n = contar(pk['B3_r2-eth1'], etiqueta=101, destino=H2_A)
    registrar('B5', 'Swap en R2: salen hacia R4 con etiqueta 101', 'paquetes con etiqueta 101',
              n > 0, 'paquetes: %d' % n)
    ip_sin = contar(pk['B3_r4-eth2'], destino=H2_A, con_mpls=False)
    con = contar(pk['B3_r4-eth2'], con_mpls=True)
    registrar('B6', 'Pop en R4: llegan a H2 como IP sin etiqueta',
              'paquetes IP hacia %s y ninguno con etiqueta' % H2_A,
              ip_sin > 0 and con == 0, 'IP sin etiqueta: %d, con etiqueta: %d' % (ip_sin, con))


def paso_c(net, con_iperf=True):
    titulo('Paso C - Dos LSP: cada direccion de H2 por su propio camino')
    log('  Clasificacion en R1: %s -> LSP-A (100/101, por R2) | %s -> LSP-B (200/201, por R3)'
        % (H2_A, H2_B))
    configurar_lsp(net, 'B')
    habilitar_entrada(net, 'B')
    ejecutar(net['r1'], 'ip route show')
    ejecutar(net['r3'], 'ip -f mpls route show')
    ejecutar(net['r4'], 'ip -f mpls route show')

    caps = capturar([Captura(net['r2'], 'r2-eth0', 'C_r2-eth0'),
                     Captura(net['r2'], 'r2-eth1', 'C_r2-eth1'),
                     Captura(net['r3'], 'r3-eth0', 'C_r3-eth0'),
                     Captura(net['r3'], 'r3-eth1', 'C_r3-eth1'),
                     Captura(net['r4'], 'r4-eth2', 'C_r4-eth2')])
    perdida_a, salida_a = ping(net['h1'], H2_A)
    perdida_b, salida_b = ping(net['h1'], H2_B)
    pk = detener(caps)
    for nombre, paquetes in pk.items():
        resumen_captura(nombre, paquetes)

    registrar('C1', 'H1 alcanza %s (LSP-A)' % H2_A, '0 % de perdida', perdida_a == 0, salida_a)
    registrar('C2', 'H1 alcanza %s (LSP-B)' % H2_B, '0 % de perdida', perdida_b == 0, salida_b)

    a_in = contar(pk['C_r2-eth0'], etiqueta=100, destino=H2_A)
    a_out = contar(pk['C_r2-eth1'], etiqueta=101, destino=H2_A)
    registrar('C3', 'LSP-A por R2: etiqueta 100 entra y 101 sale, hacia %s' % H2_A,
              'paquetes en ambas interfaces de R2', a_in > 0 and a_out > 0,
              'r2-eth0 (100): %d, r2-eth1 (101): %d' % (a_in, a_out))

    b_in = contar(pk['C_r3-eth0'], etiqueta=200, destino=H2_B)
    b_out = contar(pk['C_r3-eth1'], etiqueta=201, destino=H2_B)
    registrar('C4', 'LSP-B por R3: etiqueta 200 entra y 201 sale, hacia %s' % H2_B,
              'paquetes en ambas interfaces de R3', b_in > 0 and b_out > 0,
              'r3-eth0 (200): %d, r3-eth1 (201): %d' % (b_in, b_out))

    cruzados = (contar(pk['C_r2-eth0'], destino=H2_B, con_mpls=True)
                + contar(pk['C_r2-eth1'], destino=H2_B, con_mpls=True)
                + contar(pk['C_r3-eth0'], destino=H2_A, con_mpls=True)
                + contar(pk['C_r3-eth1'], destino=H2_A, con_mpls=True))
    registrar('C5', 'Los flujos no se mezclan: nada etiquetado hacia %s en R2 ni hacia %s en R3'
              % (H2_B, H2_A), '0 paquetes cruzados', cruzados == 0,
              'paquetes cruzados: %d' % cruzados)

    sin_a = contar(pk['C_r4-eth2'], destino=H2_A, con_mpls=False)
    sin_b = contar(pk['C_r4-eth2'], destino=H2_B, con_mpls=False)
    con = contar(pk['C_r4-eth2'], con_mpls=True)
    registrar('C6', 'R4 quita las etiquetas de ambos LSP', 'IP sin etiqueta hacia .11 y .12',
              sin_a > 0 and sin_b > 0 and con == 0,
              '.11: %d, .12: %d, con etiqueta: %d' % (sin_a, sin_b, con))

    if con_iperf:
        prueba_iperf(net)


def prueba_iperf(net):
    """Prueba de humo, no es la medicion del proyecto: TCP por cada LSP, 5 s, uno a la vez."""
    log('\n-- C7. Prueba corta con iperf3 (TCP atraviesa cada LSP)')
    if not shutil.which('iperf3'):
        registrar('C7', 'iperf3 disponible', 'iperf3 instalado', False, 'sudo apt install iperf3')
        return
    servidor = net['h2'].popen(['iperf3', '-s'], stdout=DEVNULL, stderr=DEVNULL)
    time.sleep(1)
    try:
        for id_prueba, nombre in (('C7', 'A'), ('C8', 'B')):
            destino = LSP[nombre]['destino']
            salida = ejecutar(net['h1'], 'iperf3 -c %s -t 5 -J' % destino, mostrar=False)
            mbps = 0.0
            try:
                datos = json.loads(salida[salida.index('{'):])
                mbps = datos['end']['sum_received']['bits_per_second'] / 1e6
            except (ValueError, KeyError):
                pass
            log('  iperf3 h1 -> %s (LSP-%s): %.2f Mbps recibidos' % (destino, nombre, mbps))
            registrar(id_prueba, 'TCP por el LSP-%s alcanza al menos la mitad de %d Mbps'
                      % (nombre, BW_NUCLEO), '> %.1f Mbps' % (BW_NUCLEO / 2),
                      mbps > BW_NUCLEO / 2, '%.2f Mbps' % mbps)
            time.sleep(1)
    finally:
        servidor.terminate()
        servidor.wait()


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def preparar_mpls():
    """Carga los modulos de MPLS en el host. Los sysctl se ajustan luego en cada router."""
    for modulo in ('mpls_router', 'mpls_iptunnel'):
        r = subprocess.run(['modprobe', modulo], stdout=PIPE, stderr=PIPE,
                           universal_newlines=True)
        if r.returncode != 0:
            sys.exit('No se pudo cargar %s: %s\nCorran primero: sudo bash verificar_entorno.sh'
                     % (modulo, r.stderr.strip()))
    subprocess.run(['modprobe', 'mpls_gso'], stdout=DEVNULL, stderr=DEVNULL)
    if not os.path.isdir('/proc/sys/net/mpls'):
        sys.exit('/proc/sys/net/mpls no existe: el kernel no tiene MPLS habilitado.')


def info_entorno():
    def salida(cmd):
        try:
            r = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
            return (r.stdout.strip() or r.stderr.strip())
        except OSError:
            return ''
    distro = ''
    if os.path.exists('/etc/os-release'):
        with open('/etc/os-release') as f:
            m = re.search(r'^PRETTY_NAME="?([^"\n]*)', f.read(), re.M)
            distro = m.group(1) if m else ''
    iperf3 = salida(['iperf3', '--version']) if shutil.which('iperf3') else ''
    return dict(distro=distro, kernel=os.uname().release,
                mininet=salida(['mn', '--version']), iproute2=salida(['ip', '-V']),
                iperf3=iperf3.splitlines()[0] if iperf3 else '')


def main():
    global BITACORA
    parser = argparse.ArgumentParser(description='Etapa 1: validacion de Mininet + MPLS')
    parser.add_argument('--hasta', choices=['A', 'B', 'C'], default='C',
                        help='ultimo paso a ejecutar (por defecto C)')
    parser.add_argument('--cli', action='store_true',
                        help='abre la CLI de Mininet al terminar, con la configuracion puesta')
    parser.add_argument('--sin-iperf', action='store_true', help='omite la prueba con iperf3')
    args = parser.parse_args()

    if os.geteuid() != 0:
        sys.exit('Ejecuta con sudo: sudo python3 validar_mpls.py')
    for herramienta in ('tcpdump', 'ethtool', 'ip'):
        if not shutil.which(herramienta):
            sys.exit('Falta %s. Corran primero: sudo bash verificar_entorno.sh' % herramienta)
    if args.hasta != 'A':
        preparar_mpls()

    os.makedirs(DIR_RESULTADOS, exist_ok=True)
    os.makedirs(DIR_CAPTURAS, exist_ok=True)
    BITACORA = open(os.path.join(DIR_RESULTADOS, 'etapa1_bitacora.txt'), 'w')
    entorno = info_entorno()
    log('Etapa 1 - validacion de Mininet + MPLS | %s' % datetime.datetime.now().isoformat(' ', 'seconds'))
    log('  %s | kernel %s | %s' % (entorno['distro'], entorno['kernel'], entorno['iproute2']))

    setLogLevel('warning')
    net = None
    try:
        net = construir_red()
        paso_a(net)
        if args.hasta in ('B', 'C'):
            paso_b(net)
        if args.hasta == 'C':
            paso_c(net, con_iperf=not args.sin_iperf)
        if args.cli:
            log('\nCLI de Mininet. Pruebe por ejemplo:  r2 ip -f mpls route   |   '
                'h1 ping -c 3 %s   |   exit para salir' % H2_B)
            CLI(net)
    finally:
        if net is not None:
            net.stop()

        aprobadas = sum(r['resultado'] == 'PASA' for r in RESULTADOS)
        titulo('Resumen: %d de %d pruebas pasan' % (aprobadas, len(RESULTADOS)))
        for r in RESULTADOS:
            log('  %-5s %-4s %s' % (r['resultado'], r['id'], r['descripcion']))

        resumen = dict(fecha=datetime.datetime.now().isoformat(timespec='seconds'),
                       entorno=entorno, hasta=args.hasta,
                       topologia=dict(bw_nucleo_mbps=BW_NUCLEO, bw_acceso_mbps=BW_ACCESO,
                                      mtu_nucleo=MTU_NUCLEO, h2_lsp_a=H2_A, h2_lsp_b=H2_B,
                                      lsp={k: dict(push=v['push'], swap=v['swap'],
                                                   por=v['medio']) for k, v in LSP.items()}),
                       pruebas=RESULTADOS, aprobadas=aprobadas, total=len(RESULTADOS))
        ruta = os.path.join(DIR_RESULTADOS, 'etapa1_resumen.json')
        with open(ruta, 'w') as f:
            json.dump(resumen, f, indent=2, ensure_ascii=False)
        log('\nResumen: %s\nBitacora: %s\nCapturas: %s'
            % (ruta, os.path.join(DIR_RESULTADOS, 'etapa1_bitacora.txt'), DIR_CAPTURAS))
        BITACORA.close()

    sys.exit(0 if RESULTADOS and aprobadas == len(RESULTADOS) else 1)


if __name__ == '__main__':
    main()
