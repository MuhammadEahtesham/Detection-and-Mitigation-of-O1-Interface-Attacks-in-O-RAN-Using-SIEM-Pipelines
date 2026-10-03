from scapy.all import PcapReader, PcapWriter, Ether, IP, conf
conf.verb = 0

eth = Ether(src="00:00:00:00:00:01", dst="00:00:00:00:00:02")

count = 0
pr = PcapReader('/tmp/icmp_flood.pcap')
pw = PcapWriter('/tmp/icmp_flood_clean2.pcap', linktype=1)

for p in pr:
    if p.haslayer(IP):
        pw.write(eth / p[IP])
        count += 1

pr.close()
pw.close()
print("wrote", count, "packets")
