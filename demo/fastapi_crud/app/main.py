from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="TeaForge Demo CRUD")


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0, le=10_000)


class ItemUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0, le=10_000)


class ItemOut(BaseModel):
    id: int
    name: str
    quantity: int


def _db_path() -> Path:
    env_path = os.getenv("TEAFORGE_DEMO_DB")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / "demo.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                quantity INTEGER NOT NULL
            )
            """
        )
        conn.commit()


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


@app.post("/items", response_model=ItemOut)
def create_item(payload: ItemCreate) -> ItemOut:
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "INSERT INTO items (name, quantity) VALUES (?, ?)",
                (payload.name, payload.quantity),
            )
            conn.commit()
            item_id = cursor.lastrowid
            row = conn.execute(
                "SELECT id, name, quantity FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Item name already exists") from exc
    return ItemOut(**dict(row))


@app.get("/items", response_model=list[ItemOut])
def list_items() -> list[ItemOut]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, name, quantity FROM items ORDER BY id").fetchall()
    return [ItemOut(**dict(row)) for row in rows]


@app.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: int) -> ItemOut:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, quantity FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemOut(**dict(row))


@app.put("/items/{item_id}", response_model=ItemOut)
def update_item(item_id: int, payload: ItemUpdate) -> ItemOut:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Item not found")
            conn.execute(
                "UPDATE items SET name = ?, quantity = ? WHERE id = ?",
                (payload.name, payload.quantity, item_id),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT id, name, quantity FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Item name already exists") from exc
    return ItemOut(**dict(updated))


@app.delete("/items/{item_id}")
def delete_item(item_id: int) -> dict[str, str]:
    with _connect() as conn:
        row = conn.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Item not found")
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
    return {"status": "deleted"}

