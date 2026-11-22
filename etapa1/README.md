# Etapa 1 — Validar Mininet y MPLS en el equipo

Proyecto de Redes: STP vs MPLS · Andrés Lanchimba y Emilio Puga

Esta etapa responde a lo que pidió el profesor antes de construir los escenarios:

1. Comprobar la conectividad de **un camino**.
2. Comprobar la **inserción y eliminación de etiquetas**.
3. Comprobar que funcionan **los dos LSP**, con capturas que muestren el camino y las etiquetas de cada flujo.
4. Revisar los **parámetros MPLS del kernel**, que por defecto deshabilitan el reenvío por etiquetas.

**Plazo:** semanas 1 y 2 (hasta el **28 de octubre**). Si MPLS no funciona para esa fecha, hay que acordar con el profesor un ajuste del entorno o del alcance antes de seguir.

## Contenido de la carpeta

| Archivo | Para qué sirve |
|---|---|
| `verificar_entorno.sh` | Revisa herramientas, Open vSwitch y módulos MPLS, y hace una prueba mínima de MPLS sin Mininet. |
| `validar_mpls.py` | Monta la topología base en Mininet y ejecuta los pasos A, B y C con comprobaciones automáticas. |
| `resultados/` | Se crea al correr: `etapa1_resumen.json` (PASA/FALLA de cada prueba) y `etapa1_bitacora.txt` (cada comando y su salida). |
| `capturas/` | Se crea al correr: archivos `.pcap` para abrir en Wireshark. |

---

## 0. Preparar un Ubuntu donde correr todo

Mininet y MPLS necesitan un kernel Linux con soporte MPLS. Desde Windows, la opción más segura es una **máquina virtual con Ubuntu 24.04 LTS** (22.04 también sirve).

**Máquina virtual (recomendado)**

1. Instalen VirtualBox 7 (o VMware Workstation, que es gratuito para uso personal).
2. Descarguen la ISO de Ubuntu 24.04 LTS Desktop desde https://releases.ubuntu.com/noble/. El archivo es `ubuntu-24.04.5.1-desktop-amd64.iso`: Canonical retiró la imagen 24.04.5 de escritorio porque el instalador fallaba con la «Selección extendida», y la reemplazó por la 24.04.5.1. Ojo: la página principal de ubuntu.com ahora ofrece la 26.04 por defecto, y los scripts se probaron con los paquetes de la 24.04.
   En VMware, al crear la VM elijan «I will install the operating system later» y después conecten la ISO en la unidad de CD/DVD; así se evita Easy Install.
3. Creen la VM con al menos **2 CPU, 4 GB de RAM y 30 GB de disco**, e instalen Ubuntu normalmente.
4. Si en Windows tienen WSL o Hyper-V activos, VirtualBox funciona igual pero puede ir más lento. Para este proyecto no importa: el tráfico es de pocos Mbps.

**WSL**

El kernel que trae WSL2 puede no incluir los módulos de MPLS. Pueden probarlo en un minuto corriendo `verificar_entorno.sh` dentro de WSL: si la sección 4 falla, pasen a la VM. No vale la pena compilar un kernel propio.

**Cómo llevar los archivos a la VM**

Lo más práctico es crear un repositorio en GitHub para el proyecto, compartido entre los dos, y clonarlo dentro de la VM. Así ambos trabajan sobre la misma versión y el profesor recibe un script reproducible. También pueden descargar los archivos desde el navegador de la VM.

---

## 1. Instalar los paquetes

Dentro de Ubuntu:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch iperf3 tcpdump ethtool iproute2 wireshark git
sudo systemctl enable --now openvswitch-switch
```

Durante la instalación aparecen dos preguntas:

- **iperf3** pregunta si debe arrancar como servicio al iniciar el sistema → respondan **No**.
- **Wireshark** pregunta si usuarios sin privilegios pueden capturar → da igual; aquí solo abrirán archivos `.pcap`.

Si más adelante `modprobe mpls_router` falla, instalen los módulos extra del kernel y reinicien la VM:

```bash
sudo apt install -y linux-modules-extra-$(uname -r)
```

---

## 2. Verificar el entorno

```bash
cd etapa1
sudo bash verificar_entorno.sh
```

El script revisa cinco cosas:

| Sección | Qué revisa |
|---|---|
| 1. Sistema | Distribución, kernel y si están en WSL. |
| 2. Herramientas | `mn`, `ip`, `tcpdump`, `iperf3`, `ethtool`, Wireshark y que Python importe Mininet. |
| 3. Open vSwitch y Mininet | Que OVS esté corriendo y que `mn --test pingall` funcione. OVS lo usarán en el escenario STP. |
| 4. MPLS en el kernel | Carga `mpls_router` y `mpls_iptunnel`, comprueba que exista `/proc/sys/net/mpls` y que `ip` entienda rutas MPLS. |
| 5. Prueba mínima de MPLS | Con dos namespaces, sin Mininet: muestra que con los valores por defecto no se puede, y que con los ajustes correctos una etiqueta se inserta y se quita. |

Al final debe decir:

```
Resultado: todo listo (N aviso(s)). Sigan con: sudo python3 validar_mpls.py
```

Los avisos (`[AVISO]`) no bloquean. Las fallas (`[FALLA]`) sí: revisen la sección 7 de esta guía.

---

## 3. Topología y decisiones de diseño

```
                     10.0.12.0/24               10.0.24.0/24
                r1-eth1 .1 ── .2 r2-eth0 [R2] r2-eth1 .2 ── .4 r4-eth0
               /                                                       \
 [H1] ───── [R1]                                                       [R4] ───── [H2]
 .10   r1-eth0 .1                                                 r4-eth2 .1      .11 y .12
     10.0.1.0/24                                                        10.0.2.0/24
               \                                                       /
                r1-eth2 .1 ── .3 r3-eth0 [R3] r3-eth1 .3 ── .4 r4-eth1
                     10.0.13.0/24               10.0.34.0/24
```

| Enlace | Interfaces | Red | Capacidad |
|---|---|---|---|
| H1 – R1 | h1-eth0 / r1-eth0 | 10.0.1.0/24 | 100 Mbps |
| R1 – R2 | r1-eth1 / r2-eth0 | 10.0.12.0/24 | 10 Mbps |
| R1 – R3 | r1-eth2 / r3-eth0 | 10.0.13.0/24 | 10 Mbps |
| R2 – R4 | r2-eth1 / r4-eth0 | 10.0.24.0/24 | 10 Mbps |
| R3 – R4 | r3-eth1 / r4-eth1 | 10.0.34.0/24 | 10 Mbps |
| R4 – H2 | r4-eth2 / h2-eth0 | 10.0.2.0/24 | 100 Mbps |

| LSP | Destino en H2 | R1 inserta | Intercambio | R4 quita | Camino |
|---|---|---|---|---|---|
| LSP-A | 10.0.2.11 | 100 | R2: 100 → 101 | 101 | R1 → R2 → R4 |
| LSP-B | 10.0.2.12 | 200 | R3: 200 → 201 | 201 | R1 → R3 → R4 |

**Decisiones que deben quedar documentadas en el informe**

1. **Cómo R1 separa los flujos.** H2 tiene dos direcciones, y R1 tiene una ruta `/32` etiquetada para cada una. El flujo hacia `.11` entra al LSP-A y el flujo hacia `.12` entra al LSP-B. Es la simplificación que sugirió el profesor. En el escenario STP, H2 tendrá las mismas dos direcciones y se usará exactamente el mismo tráfico.
2. **Camino de regreso.** Las respuestas de H2 hacia H1 (los ACK de TCP y los ICMP echo reply) vuelven por IP normal, siempre por R2. Por eso se desactiva el filtro de ruta inversa (`rp_filter=0`): la respuesta de `.12` entra a R1 por R2 aunque la ida salió por R3, y con el filtro estricto R1 la descartaría.
3. **Capacidades.** Núcleo a 10 Mbps y accesos a 100 Mbps, para que los accesos nunca limiten la comparación (el profesor pidió más de 20 Mbps).
4. **MTU del núcleo en 1600.** Cada etiqueta MPLS agrega 4 bytes. Con MTU 1600 en el núcleo, un paquete IP de 1500 bytes etiquetado cabe sin fragmentar. Es lo que se hace en redes MPLS reales.
5. **Offloads desactivados** (`ethtool -K ... tso off gso off gro off`). Así cada paquete tiene su tamaño real en el cable y las capturas muestran checksums correctos.
6. **Parámetros MPLS por router.** `net.mpls.platform_labels=1000` en cada router y `net.mpls.conf.<interfaz>.input=1` solo en las interfaces que reciben paquetes etiquetados (r2-eth0, r3-eth0, r4-eth0 y r4-eth1). Estos valores son **por namespace de red**: como en Mininet cada router tiene el suyo, hay que ajustarlos dentro de cada router y no una sola vez en la VM.

---

## 4. Ejecutar la validación

```bash
sudo python3 validar_mpls.py
```

Tarda menos de un minuto. Otras formas de correrlo:

```bash
sudo python3 validar_mpls.py --hasta A     # solo el paso A (no necesita MPLS)
sudo python3 validar_mpls.py --hasta B     # pasos A y B
sudo python3 validar_mpls.py --sin-iperf   # omite la prueba corta de iperf3
sudo python3 validar_mpls.py --cli         # al terminar abre la CLI de Mininet (sección 6)
```

Al arrancar pueden aparecer líneas como `*** Error: Warning: sch_htb: quantum of class 50001 is big`. Aunque digan «Error», son avisos del limitador de ancho de banda y no afectan nada.

### Paso A — Un camino IP sin etiquetas

Se cargan rutas estáticas para que todo vaya por R1 → R2 → R4, y H1 hace ping a las dos direcciones de H2 mientras se captura en R2 y en R3.

```text
r1: ip route add 10.0.2.0/24 via 10.0.12.2
r2: ip route add 10.0.1.0/24 via 10.0.12.1
r2: ip route add 10.0.2.0/24 via 10.0.24.4
r4: ip route add 10.0.1.0/24 via 10.0.24.2
```

### Paso B — Inserción, intercambio y eliminación de etiquetas (LSP-A)

Primero se demuestra lo que advierte la documentación del kernel:

- **B1.** Con `platform_labels=0` (valor por defecto), el kernel rechaza crear la ruta de la etiqueta 100.
- **B2.** Con `platform_labels=1000` pero `input=0` en r2-eth0, R1 sí etiqueta los paquetes y estos llegan a R2 (se ven en la captura), pero R2 los descarta y el ping falla.

Luego se habilita `input=1` y se comprueba cada operación:

```text
r1: ip route add 10.0.2.11/32 encap mpls 100 via 10.0.12.2 dev r1-eth1    # push
r2: ip -f mpls route add 100 as 101 via inet 10.0.24.4 dev r2-eth1        # swap
r4: ip -f mpls route add 101 via inet 10.0.2.11 dev r4-eth2               # pop
```

### Paso C — Los dos LSP

Se agrega el LSP-B por R3 (etiquetas 200 → 201) y se captura en las dos interfaces de R2, las dos de R3 y la de R4 hacia H2. El script comprueba que cada flujo va solo por su camino, que cada router intercambia la etiqueta correcta y que R4 entrega a H2 paquetes IP sin etiqueta. Al final corre iperf3 durante 5 segundos por cada LSP, uno a la vez, solo para confirmar que TCP atraviesa el LSP. **No es la medición del proyecto.**

### Pruebas y resultado esperado

| Prueba | Qué comprueba | Esperado |
|---|---|---|
| A1, A2 | H1 alcanza .11 y .12 por IP | 0 % de pérdida |
| A3 | El tráfico pasa por R2 y no por R3 | paquetes en r2-eth0, ninguno en r3-eth0 |
| B1 | `platform_labels=0` impide crear rutas de etiquetas | error al crear la ruta |
| B2 | `input=0` descarta paquetes etiquetados | 100 % de pérdida, etiqueta 100 visible en r2-eth0 |
| B3 | Ping por el LSP-A | 0 % de pérdida |
| B4, B5, B6 | Push en R1, swap en R2, pop en R4 | etiqueta 100, luego 101, luego IP sin etiqueta |
| C1, C2 | Ping a .11 y .12 con los dos LSP | 0 % de pérdida |
| C3, C4 | Etiquetas de cada LSP en su router intermedio | 100/101 en R2, 200/201 en R3 |
| C5 | Los flujos no se mezclan | 0 paquetes etiquetados cruzados |
| C6 | R4 quita las etiquetas de ambos LSP | IP sin etiqueta hacia .11 y .12 |
| C7, C8 | TCP atraviesa cada LSP | más de 5 Mbps (el núcleo es de 10) |

Si todo está bien, el final de la salida es:

```
Resumen: 17 de 17 pruebas pasan
```

El script termina con código 0 si todas pasan y 1 si alguna falla. El detalle de cada falla queda en `resultados/etapa1_resumen.json` y en `resultados/etapa1_bitacora.txt`.

---

## 5. Revisar las capturas en Wireshark

Abran las capturas como usuario normal (los archivos quedan legibles):

```bash
wireshark capturas/C_r2-eth0.pcap &
```

| Captura | Qué debe verse |
|---|---|
| `B2_r2-eth0_input0.pcap` | Paquetes con etiqueta 100 que llegan a R2 sin respuesta: R2 los descarta porque `input=0`. |
| `C_r2-eth0.pcap` / `C_r2-eth1.pcap` | Pings hacia 10.0.2.11 con etiqueta 100 al entrar a R2 y 101 al salir. |
| `C_r3-eth0.pcap` / `C_r3-eth1.pcap` | Pings hacia 10.0.2.12 con etiqueta 200 al entrar a R3 y 201 al salir. |
| `C_r4-eth2.pcap` | Paquetes IP sin etiqueta hacia .11 y .12: R4 ya quitó la etiqueta. |

Filtros útiles: `mpls`, `mpls.label == 100`, `mpls && ip.dst == 10.0.2.12`. Al seleccionar un paquete, en el panel de detalle aparece la capa **MultiProtocol Label Switching Header** con la etiqueta, el bit de fondo de pila (S) y el TTL.

En `C_r2-eth0.pcap` también aparecen paquetes **sin** etiqueta con origen .11 o .12: son las respuestas que vuelven por IP (decisión 2 de la sección 3).

**Para el informe**, guarden capturas de pantalla de un mismo ping (mismo número de secuencia ICMP) visto en `C_r2-eth0` con etiqueta 100 y en `C_r2-eth1` con etiqueta 101, y lo mismo para R3 con 200 y 201. Con eso quedan demostrados el camino y las etiquetas de cada flujo.

---

## 6. Explorar a mano con la CLI de Mininet

```bash
sudo python3 validar_mpls.py --cli
```

Dentro de la CLI, el primer nombre indica en qué nodo corre el comando:

```
mininet> r1 ip route                          # rutas IP y rutas con encap mpls
mininet> r2 ip -f mpls route                  # tabla de etiquetas de R2
mininet> r4 ip -f mpls route
mininet> r2 sysctl net.mpls.platform_labels
mininet> r2 sysctl net.mpls.conf.r2-eth0.input
mininet> h1 ping -c 3 10.0.2.12
mininet> exit
```

Para entender qué pasa al tocar un parámetro, prueben apagar la entrada en R3 y repetir el ping a .12:

```
mininet> r3 sysctl -w net.mpls.conf.r3-eth0.input=0
mininet> h1 ping -c 3 10.0.2.12               # falla
mininet> r3 sysctl -w net.mpls.conf.r3-eth0.input=1
mininet> h1 ping -c 3 10.0.2.12               # vuelve a funcionar
```

---

## 7. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `modprobe: FATAL: Module mpls_router not found` | Faltan los módulos extra del kernel, o están en WSL | `sudo apt install linux-modules-extra-$(uname -r)` y reiniciar; en WSL, usar la VM. |
| `RTNETLINK answers: File exists` al arrancar | Quedó una red de Mininet de una corrida anterior | `sudo mn -c` y volver a correr. |
| `Error: Label >= configured maximum in platform_labels` fuera del paso B1 | Ese router no tiene `platform_labels` configurado | `rX sysctl net.mpls.platform_labels` en la CLI. |
| B3 o C1/C2 con 100 % de pérdida | Falta `input=1` en la interfaz que recibe etiquetas | Revisar con `rX sysctl net.mpls.conf.<intf>.input`. |
| C5 falla | Una ruta `/32` de R1 apunta al camino equivocado | `r1 ip route` y comparar con la tabla de LSP. |
| C7/C8 con muy pocos Mbps | Offloads activos o un problema de MTU | `h1 ethtool -k h1-eth0 \| grep segmentation` y `r2 ip link` para ver la MTU. |
| `Open vSwitch no responde` | El servicio no está activo | `sudo systemctl enable --now openvswitch-switch`. |
| `tcpdump: ... Permission denied` | Restricción de tcpdump al escribir archivos | El script ya usa `-Z root`; comprueben que la carpeta no esté en un disco compartido con Windows. |

Si algo falla y no se arregla con esta tabla, guarden `resultados/etapa1_bitacora.txt` y la salida completa del script.

---

## 8. Cierre de la etapa (antes del 28 de octubre)

- [ ] `verificar_entorno.sh` termina con «todo listo».
- [ ] `validar_mpls.py` termina con 17 de 17 pruebas.
- [ ] Capturas de pantalla de Wireshark de los dos LSP (sección 5).
- [ ] `etapa1_resumen.json`, la bitácora y los `.pcap` guardados en el repositorio.
- [ ] Un párrafo en el borrador del informe con las decisiones de la sección 3.
- [ ] **Ambos** corrieron el script y pueden explicar qué hace cada `sysctl` y cada ruta (lo pidió el profesor).

Si para esa fecha MPLS no funciona en ningún equipo, toca escribirle al profesor antes de seguir.

## 9. Lo que sigue (semanas 3 y 4)

- Pasar la topología a un archivo YAML editable que lean los dos escenarios.
- Escenario STP con Open vSwitch sobre los mismos enlaces, con H2 usando las mismas dos direcciones.
- Demostración breve de la tormenta de broadcast, solo dentro de Mininet.
- Script de medición con los dos flujos simultáneos de iperf3, cinco repeticiones como mínimo, y resultados en JSON.
