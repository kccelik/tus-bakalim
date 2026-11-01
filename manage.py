"""
User management for TusBakalım (run from the project folder with .venv active).

    python manage.py add-user ornek_kullanici
    python manage.py set-password ornek_kullanici
    python manage.py list-users
    python manage.py delete-user ornek_kullanici
"""
import argparse
import getpass
import sqlite3
import sys

from tusbakalim.storage import progress as auth


def ask_password():
    pw = getpass.getpass("Şifre: ")
    if len(pw) < 6:
        sys.exit("Şifre en az 6 karakter olmalı.")
    if getpass.getpass("Şifre (tekrar): ") != pw:
        sys.exit("Şifreler eşleşmiyor.")
    return pw


def main():
    p = argparse.ArgumentParser(description="TusBakalım users")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("add-user", "set-password", "delete-user"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list-users")
    args = p.parse_args()

    auth.init_db()

    if args.cmd == "add-user":
        try:
            auth.create_user(args.username, ask_password())
        except sqlite3.IntegrityError:
            sys.exit(f"'{args.username}' zaten var.")
        print(f"Kullanıcı eklendi: {args.username}")

    elif args.cmd == "set-password":
        if not auth.set_password(args.username, ask_password()):
            sys.exit(f"'{args.username}' bulunamadı.")
        print("Şifre güncellendi.")

    elif args.cmd == "delete-user":
        with auth.connect() as conn:
            n = conn.execute("DELETE FROM users WHERE username = ?", (args.username,)).rowcount
        print("Silindi." if n else "Bulunamadı.")

    elif args.cmd == "list-users":
        with auth.connect() as conn:
            rows = conn.execute(
                """SELECT u.username, u.created_at, COUNT(a.id) AS n,
                          COALESCE(SUM(a.correct), 0) AS ok
                   FROM users u LEFT JOIN attempts a ON a.user_id = u.id
                   GROUP BY u.id ORDER BY u.id"""
            ).fetchall()
        if not rows:
            print("Henüz kullanıcı yok.")
        for r in rows:
            print(f"{r['username']:<20} oluşturuldu {r['created_at'][:10]}  "
                  f"{r['n']} cevap, {r['ok']} doğru")


if __name__ == "__main__":
    main()
