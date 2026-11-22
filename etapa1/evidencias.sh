#!/usr/bin/env bash
# Etapa 1 - resumen de las capturas que deja validar_mpls.py
#
# Para cada .pcap cuenta los paquetes ICMP por tipo, destino y etiqueta MPLS,
# y muestra al lado lo que se espera ver. Sirve para revisar todo de una vez
# antes de tomar las capturas de pantalla en Wireshark.
#
# Uso (dentro de la carpeta etapa1, despues de correr validar_mpls.py):
#   bash evidencias.sh | tee resultados/etapa1_evidencias.txt

set -u
DIR="${1:-capturas}"

if ! command -v tshark >/dev/null 2>&1; then
    echo "Falta tshark. Instalenlo con: sudo apt install -y tshark"
    exit 1
fi

ORDEN="A_r2-eth0 A_r3-eth0 B2_r2-eth0_input0 B3_r2-eth0 B3_r2-eth1 B3_r4-eth2
       C_r2-eth0 C_r2-eth1 C_r3-eth0 C_r3-eth1 C_r4-eth2"

declare -A ESPERADO=(
    [A_r2-eth0]="Paso A, entrada de R2: pings a .11 y .12 y sus respuestas, todo sin etiqueta"
    [A_r3-eth0]="Paso A, entrada de R3: ningun ping (todo va por R2)"
    [B2_r2-eth0_input0]="Paso B2, input=0: requests con etiqueta 100 y ninguna respuesta"
    [B3_r2-eth0]="Push en R1: etiqueta 100 hacia .11; respuestas sin etiqueta"
    [B3_r2-eth1]="Swap en R2: etiqueta 101 hacia .11; respuestas sin etiqueta"
    [B3_r4-eth2]="Pop en R4: requests hacia .11 sin etiqueta; respuestas sin etiqueta"
    [C_r2-eth0]="LSP-A: 100 hacia .11; nada etiquetado hacia .12; respuestas sin etiqueta"
    [C_r2-eth1]="LSP-A: 101 hacia .11; nada etiquetado hacia .12; respuestas sin etiqueta"
    [C_r3-eth0]="LSP-B: 200 hacia .12; nada hacia .11; ninguna respuesta (vuelven por R2)"
    [C_r3-eth1]="LSP-B: 201 hacia .12; nada hacia .11; ninguna respuesta (vuelven por R2)"
    [C_r4-eth2]="R4 hacia H2: requests a .11 y .12 sin etiqueta; respuestas sin etiqueta"
)

for n in $ORDEN; do
    f="$DIR/$n.pcap"
    echo "== $n"
    echo "   esperado: ${ESPERADO[$n]}"
    if [ ! -r "$f" ]; then
        echo "   no se encuentra o no se puede leer $f"
        continue
    fi
    visto=$(tshark -r "$f" -Y icmp -T fields -E separator=' ' \
                -e icmp.type -e ip.dst -e mpls.label 2>/dev/null |
            awk '{
                if ($1 == 8)      t = "echo request"
                else if ($1 == 0) t = "echo reply  "
                else              t = "icmp tipo " $1
                l = ($3 == "") ? "sin etiqueta" : "etiqueta " $3
                print t "  hacia " $2 "  " l
            }' | sort | uniq -c)
    if [ -z "$visto" ]; then
        echo "   visto:    ningun paquete ICMP"
    else
        echo "   visto:"
        echo "$visto" | sed 's/^/   /'
    fi
done
