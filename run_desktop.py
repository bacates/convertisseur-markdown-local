"""Démarre la version portable de bureau, sans navigateur ni Qt."""

from app.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
