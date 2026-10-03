import csv, statistics
Â
# flag a window if any feature is more than 3 standard deviations from the benign mean

FEATURES = ["pkts","bytes","mean_size","std_size","unique_dports",
            "syn_count","tls_handshake","icmp_frac"]
THRESHOLD = 3.0

# Reads a CSV and returns a list of windows, each a dict of the eight features as numbers.

def load(path):
    r = csv.DictReader(open(path))
    return [{k: float(row[k]) for k in FEATURES} for row in r]

# computes the mean and standard deviation across all benign training windows. That pair train and mean is the entire model

train = load("benign_train.csv")
mean = {f: statistics.mean(w[f] for w in train) for f in FEATURES}
std  = {f: max(statistics.pstdev(w[f] for w in train), 1e-6) for f in FEATURES} # tls_handshake is 0 in every benign window, so its true standard deviation is 0. So divide it with a verz small number

# Scoring a window 

def flagged(w):
    return max(abs(w[f] - mean[f]) / std[f] for f in FEATURES) > THRESHOLD

# Counts how many windows in a file get flagged (True sums as 1).
def evaluate(path, is_attack):
    data = load(path)
    flags = sum(flagged(w) for w in data)
    return len(data), flags, is_attack

# the model was trained only on benign_train. It has never seen benign_test, the TLS attack, or the ICMP attack
# Flags on benign_test are false positives , normal traffic wrongly flagged.
# Flags on the attack files are detections , attacks correctly caught
# So the loop body runs three times, feeding each file through flagged() and counting how many windows get flagged

for name, path, atk in [("benign_test","benign_test.csv",False),
                        ("tls_flood","win_tls.csv",True),
                        ("icmp_flood","win_icmp.csv",True)]:
    n, f, a = evaluate(path, atk)
    kind = "detected" if a else "false positives"
    print(f"{name:12s} {f}/{n} {kind} ({100*f/n:.1f}%)")
