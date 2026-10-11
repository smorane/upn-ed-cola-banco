"""Motor académico de transferencias ficticias; cola enlazada y SQLite."""

import sqlite3
import uuid
from presentacion import referencia, consultar_datos
from decimal import Decimal, InvalidOperation


class Nodo:
    """Cada nodo guarda un ID y un enlace al siguiente nodo."""

    def __init__(self, valor):
        self.valor = valor
        self.siguiente = None


class ColaEnlazada:
    def __init__(self):
        self.frente = None
        self.final = None
        self.tamano = 0

    def encolar(self, valor):
        """Agrega al final sin recorrer toda la cola."""
        nuevo = Nodo(valor)
        if self.final:
            self.final.siguiente = nuevo
        else:
            self.frente = nuevo
        self.final = nuevo
        self.tamano += 1

    def desencolar(self):
        """Retira el frente: la primera operación que estaba esperando."""
        if self.frente is None:
            return None
        valor = self.frente.valor
        self.frente = self.frente.siguiente
        self.tamano -= 1
        if self.frente is None:
            self.final = None
        return valor

    def primeros(self, limite=8):
        valores = []
        nodo = self.frente
        while nodo is not None and len(valores) < limite:
            valores.append(nodo.valor)
            nodo = nodo.siguiente
        return valores


class Motor:
    def __init__(self, ruta):
        self.db = sqlite3.connect(ruta)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS transferencias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          clave_peticion TEXT NOT NULL UNIQUE,
          cuenta_destino TEXT NOT NULL,
          monto_centimos INTEGER NOT NULL CHECK(monto_centimos>0),
          modo TEXT NOT NULL CHECK(modo IN ('normal','temporal','permanente')),
          estado TEXT NOT NULL CHECK(estado IN ('pendiente','completada','fallida')),
          intentos INTEGER NOT NULL DEFAULT 0 CHECK(intentos BETWEEN 0 AND 3),
          turno INTEGER NOT NULL,
          creada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_pendientes ON transferencias(estado,turno);
        CREATE TABLE IF NOT EXISTS eventos(
          id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
          transferencia_id INTEGER NOT NULL REFERENCES transferencias(id),
          estado TEXT NOT NULL, detalle TEXT NOT NULL,
          fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_eventos_transferencia ON eventos(transferencia_id);
        PRAGMA user_version=2;
        """)
        self.cola = ColaEnlazada()
        for r in self.db.execute(
            "SELECT id FROM transferencias WHERE estado='pendiente' ORDER BY turno"
        ):
            self.cola.encolar(r["id"])
        self.turno = self.db.execute(
            "SELECT COALESCE(MAX(turno),0) FROM transferencias"
        ).fetchone()[0]

    @staticmethod
    def referencia(id):
        return referencia(id)

    def evento(self, id, estado, detalle):
        self.db.execute(
            "INSERT INTO eventos(transferencia_id,estado,detalle) VALUES(?,?,?)",
            (id, estado, detalle),
        )

    def recibir(self, cuenta, monto, clave_peticion, modo="normal"):
        if (
            not isinstance(cuenta, str)
            or not cuenta.isascii()
            or not cuenta.isdigit()
            or not 6 <= len(cuenta) <= 20
        ):
            raise ValueError("Use una cuenta ficticia de 6 a 20 dígitos, sin espacios.")
        if modo not in ("normal", "temporal", "permanente"):
            raise ValueError("Escenario inválido.")
        try:
            clave = str(uuid.UUID(str(clave_peticion)))
        except (ValueError, AttributeError):
            raise ValueError("Clave de petición inválida.")
        try:
            monto_soles = Decimal(str(monto))
            if (
                not monto_soles.is_finite()
                or not 0 < monto_soles <= 1000000
                or monto_soles * 100 != (monto_soles * 100).to_integral_value()
            ):
                raise ValueError(
                    "Monto positivo, hasta S/ 1 000 000 y máximo dos decimales."
                )
        except InvalidOperation:
            raise ValueError("Monto inválido; use punto decimal.")
        # Guardamos enteros para conservar exactamente los céntimos.
        centimos = int(monto_soles * 100)
        existente = self.db.execute(
            "SELECT * FROM transferencias WHERE clave_peticion=?", (clave,)
        ).fetchone()
        if existente:
            if (
                existente["cuenta_destino"],
                existente["monto_centimos"],
                existente["modo"],
            ) != (cuenta, centimos, modo):
                raise ValueError("La petición ya existe con otros datos.")
            return {
                "id": existente["id"],
                "referencia": self.referencia(existente["id"]),
                "nueva": False,
            }
        turno = self.turno + 1
        # El bloque confirma juntos la transferencia y su evento.
        with self.db:
            cur = self.db.execute(
                """INSERT INTO transferencias
              (clave_peticion,cuenta_destino,monto_centimos,modo,estado,turno)
              VALUES(?,?,?,?,'pendiente',?)""",
                (clave, cuenta, centimos, modo, turno),
            )
            id = cur.lastrowid
            self.evento(id, "pendiente", "Agregada al final de la cola")
        self.turno = turno
        self.cola.encolar(id)
        return {"id": id, "referencia": self.referencia(id), "nueva": True}

    def procesar(self):
        if self.cola.frente is None:
            return None
        id = self.cola.frente.valor  # Leer sin retirar hasta confirmar SQLite.
        r = self.db.execute("SELECT * FROM transferencias WHERE id=?", (id,)).fetchone()
        intento = r["intentos"] + 1
        fallo = r["modo"] == "permanente" or (r["modo"] == "temporal" and intento == 1)
        # Primero decidimos el resultado de este intento.
        if not fallo:
            estado = "completada"
            detalle = "Transferencia completada"
        elif intento >= 3:
            estado = "fallida"
            detalle = "Tercer fallo; requiere revisión"
        else:
            estado = "pendiente"
            detalle = "Fallo temporal; vuelve al final"

        # Una operación pendiente recibe un nuevo lugar al final de la cola.
        if estado == "pendiente":
            turno = self.turno + 1
        else:
            turno = r["turno"]
        # Guarda el resultado antes de retirar la transferencia.
        with self.db:
            self.db.execute(
                "UPDATE transferencias SET estado=?,intentos=?,turno=? WHERE id=?",
                (estado, intento, turno, id),
            )
            self.evento(id, estado, detalle)
        self.cola.desencolar()
        # Si necesita otro intento, vuelve al final.
        if estado == "pendiente":
            self.turno = turno
            self.cola.encolar(id)
        return {
            "id": id,
            "referencia": self.referencia(id),
            "estado": estado,
            "intentos": intento,
            "detalle": detalle,
        }

    def estado(self):
        conteos = dict(
            self.db.execute(
                "SELECT estado,COUNT(*) FROM transferencias GROUP BY estado"
            ).fetchall()
        )
        cola = []
        for id in self.cola.primeros():
            r = dict(
                self.db.execute(
                    "SELECT * FROM transferencias WHERE id=?", (id,)
                ).fetchone()
            )
            r.pop("clave_peticion")
            r["referencia"] = self.referencia(id)
            cola.append(r)
        historial = []
        for fila in self.db.execute(
            "SELECT id,cuenta_destino,monto_centimos,estado,intentos FROM transferencias WHERE estado!='pendiente' ORDER BY id DESC LIMIT 10"
        ):
            historial.append(dict(fila))
        eventos = []
        for fila in self.db.execute(
            "SELECT * FROM eventos ORDER BY id_evento DESC LIMIT 10"
        ):
            eventos.append(dict(fila))
        return {
            "conteos": conteos,
            "pendientes": self.cola.tamano,
            "cola": cola,
            "historial": historial,
            "eventos": eventos,
        }

    def datos(self):
        return consultar_datos(self.db)