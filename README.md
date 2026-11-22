# STP vs MPLS en Mininet

Proyecto final de Redes de Computadoras · Andrés Lanchimba y Emilio Puga

Herramienta en Python y Mininet que compara STP (conmutación de capa 2 con Open vSwitch) y MPLS (reenvío por etiquetas del kernel de Linux) sobre la misma topología y con el mismo tráfico. Al final, un dashboard reúne los resultados de los dos escenarios.

## Estado

| Etapa | Qué incluye | Estado |
|---|---|---|
| [Etapa 1](etapa1/) | Validar Mininet y MPLS: un camino IP, inserción, intercambio y eliminación de etiquetas, y los dos LSP | Completa: 17 de 17 pruebas |
| Etapa 2 | Topología en YAML, escenario STP con Open vSwitch y demostración de la tormenta de broadcast | Pendiente |

## Topología base

```
            ┌──── R2 ────┐
H1 ──── R1 ─┤            ├─ R4 ──── H2 (10.0.2.11 y 10.0.2.12)
            └──── R3 ────┘
```

- Núcleo a 10 Mbps con MTU 1600; accesos H1–R1 y R4–H2 a 100 Mbps.
- **LSP-A:** tráfico hacia 10.0.2.11 por R2, etiquetas 100 → 101.
- **LSP-B:** tráfico hacia 10.0.2.12 por R3, etiquetas 200 → 201.
- Las respuestas de H2 vuelven por IP normal, siempre por R2.

Las direcciones, interfaces y decisiones de diseño están en la sección 3 de [etapa1/README.md](etapa1/README.md).

## Requisitos

- Ubuntu 24.04 LTS, de preferencia en una máquina virtual. El kernel de WSL2 puede no traer MPLS.
- Kernel con los módulos `mpls_router` y `mpls_iptunnel`.
- Paquetes:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch iperf3 tcpdump ethtool iproute2 wireshark tshark git
sudo systemctl enable --now openvswitch-switch
```

## Cómo reproducir la etapa 1

```bash
git clone https://github.com/USUARIO/stp-vs-mpls.git
cd stp-vs-mpls/etapa1
sudo bash verificar_entorno.sh      # debe terminar con «todo listo»
sudo python3 validar_mpls.py        # debe terminar con «17 de 17 pruebas pasan»
sudo chown -R $USER:$USER .         # el script crea resultados/ y capturas/ como root
bash evidencias.sh                  # en cada captura, «visto» debe coincidir con «esperado»
```

La guía paso a paso, con la instalación de la VM y los problemas frecuentes, está en [etapa1/README.md](etapa1/README.md).

## Estructura

```
stp-vs-mpls/
├── README.md                  este archivo
├── .gitignore
└── etapa1/
    ├── README.md              guía de la etapa 1
    ├── verificar_entorno.sh   revisa herramientas, Open vSwitch y MPLS del kernel
    ├── validar_mpls.py        monta la topología y ejecuta las 17 pruebas
    ├── evidencias.sh          resume las capturas con tshark
    ├── verificacion_*.txt     salida de verificar_entorno.sh de cada integrante
    ├── validacion_*.txt       salida de validar_mpls.py de cada integrante
    ├── resultados/            etapa1_resumen.json, etapa1_bitacora.txt, etapa1_evidencias.txt
    ├── capturas/              los 11 archivos .pcap
    └── figuras/               capturas de pantalla de Wireshark
```

## Resultados de la etapa 1

### Corridas

| Integrante | Fecha | Ubuntu | Kernel | Virtualización | Resultado |
|---|---|---|---|---|---|
| Andrés | 18 oct 2026 | 24.04.5 LTS | 7.0.0-38-generic | VMware | 17 de 17 |
| Andrés | 21 nov 2026 | 24.04.5 LTS | 7.0.0-38-generic | VMware | 17 de 17 |
| Emilio | | | | | |

Los archivos `resultados/` y `capturas/` son de la corrida de Andrés del 21 de noviembre. De cada integrante quedan sus salidas en `verificacion_*.txt` y `validacion_*.txt`.

### Figuras

| Figura | Captura | Qué muestra |
|---|---|---|
| [1a](etapa1/figuras/fig1a_un_camino_r2-eth0.png) | `A_r2-eth0` | Paso A: pings a .11 y .12 sin etiqueta, pasando por R2 |
| [1b](etapa1/figuras/fig1b_un_camino_r3-eth0.png) | `A_r3-eth0` | Paso A: ningún ping pasa por R3 |
| [2](etapa1/figuras/fig2_input0_r2-eth0.png) | `B2_r2-eth0_input0` | Con `input=0`, R2 recibe la etiqueta 100 y descarta el paquete: no hay respuesta |
| [3](etapa1/figuras/fig3_push_r2-eth0.png) | `B3_r2-eth0` | Push en R1: etiqueta 100, TTL 63, 102 bytes |
| [4](etapa1/figuras/fig4_swap_r2-eth1.png) | `B3_r2-eth1` | Swap en R2: etiqueta 101, TTL 62 |
| [5](etapa1/figuras/fig5_pop_r4-eth2.png) | `B3_r4-eth2` | Pop en R4: IP sin etiqueta, 98 bytes, TTL 61 |
| [6a](etapa1/figuras/fig6a_lspA_r2-eth0.png) · [6b](etapa1/figuras/fig6b_lspA_r2-eth1.png) | `C_r2-eth0` · `C_r2-eth1` | LSP-A: 100 al entrar a R2 y 101 al salir, hacia .11 |
| [7a](etapa1/figuras/fig7a_lspB_r3-eth0.png) · [7b](etapa1/figuras/fig7b_lspB_r3-eth1.png) | `C_r3-eth0` · `C_r3-eth1` | LSP-B: 200 al entrar a R3 y 201 al salir, hacia .12 |

Entre las figuras 3 y 5 el paquete pierde 4 bytes (la etiqueta) y el TTL baja uno en cada salto.

En las figuras 7a y 7b Wireshark marca «no response found!», pero el ping sí funcionó (prueba C2, 0 % de pérdida). La respuesta vuelve por R2 y por eso no aparece en las capturas de R3. En la figura 2, en cambio, no hay respuesta porque R2 descartó el paquete.
