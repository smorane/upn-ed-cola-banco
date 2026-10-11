"""Convierte los datos internos en valores fáciles de leer en pantalla."""

from decimal import Decimal


def referencia(numero):
    """El número 1 se muestra como TR-0001; el 25, como TR-0025."""
    numero_con_ceros = str(numero).zfill(4)
    return "TR-" + numero_con_ceros


def soles(centimos):
    """10000 céntimos se muestran como S/ 100.00."""
    monto = Decimal(centimos) / Decimal(100)
    return f"S/ {monto:.2f}"


def consultar_datos(conexion, limite=100):
    """Solo consulta: no cambia la base ni expone claves de petición."""
    transferencias = []
    consulta = """SELECT id, cuenta_destino, monto_centimos, estado,
                         intentos, creada_en
                  FROM transferencias ORDER BY id DESC LIMIT ?"""
    for fila in conexion.execute(consulta, (limite,)):
        transferencia = {
            "Referencia": referencia(fila["id"]),
            "Cuenta de destino": fila["cuenta_destino"],
            "Monto": soles(fila["monto_centimos"]),
            "Estado": fila["estado"],
            "Intentos": fila["intentos"],
            "Fecha (UTC)": fila["creada_en"],
        }
        transferencias.append(transferencia)

    eventos = []
    consulta = """SELECT transferencia_id, estado, detalle, fecha
                  FROM eventos ORDER BY id_evento DESC LIMIT ?"""
    for fila in conexion.execute(consulta, (limite,)):
        evento = {
            "Referencia": referencia(fila["transferencia_id"]),
            "Estado": fila["estado"],
            "Detalle": fila["detalle"],
            "Fecha (UTC)": fila["fecha"],
        }
        eventos.append(evento)

    return {"transferencias": transferencias, "eventos": eventos}
