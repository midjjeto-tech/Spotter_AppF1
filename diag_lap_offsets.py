"""Run during F1 25 race to find sector time byte offsets. Ctrl+C to stop."""
import socket, struct

HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
LAP_DATA_SIZE = 57

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 20777))
print("Listening on port 20777...")
while True:
    data, _ = sock.recvfrom(4096)
    hdr = struct.unpack_from(HEADER_FORMAT, data)
    if hdr[5] != 2: continue  # PACKET_LAP_DATA
    pidx = hdr[10]
    base = HEADER_SIZE + pidx * LAP_DATA_SIZE
    if base + LAP_DATA_SIZE > len(data): continue
    last_ms = struct.unpack_from("<I", data, base)[0]
    if last_ms == 0: continue
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}"
         f"  pit_status={data[base+34]}")
    # CarDamageData — другой пакет (packet 10), другой base/stride; не печатается
    # здесь автоматически. Для сверки байтов 24/25/26 (крылья), 27/28/29 (аэро/пол),
    # 32 (коробка), 33 (двигатель) — временно взять реальное повреждение в игре и
    # вручную сравнить со значением из parse_player_damage()'s "wing_damage" и т.п.
    # (эти байты — из ДРУГОГО типа пакета, не LapData, где выведен этот print).
    # Candidate uint16 values — find two that sum close to last_ms
    for off in [8, 10, 12, 14, 16, 18, 20, 22]:
        v = struct.unpack_from("<H", data, base + off)[0]
        print(f"  offset {off:2d}: {v:6d}ms = {v/1000:.3f}s")
