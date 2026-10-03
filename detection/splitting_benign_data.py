
import csv
rows = list(csv.reader(open('win_benign.csv')))
header, data = rows[0], rows[1:]
cut = int(len(data) * 0.8)
for name, part in [('benign_train.csv', data[:cut]),
                   ('benign_test.csv',  data[cut:])]:
    with open(name, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(part)
print(f"train {cut}, test {len(data)-cut}")
