"""Servidor local de un solo escritor. Ejecutar: python3 app.py."""
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse, json, logging
from motor import Motor

class Handler(BaseHTTPRequestHandler):
    def respuesta(self, data, code=200):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(raw)

    def do_GET(self):
        try:
            if self.path=='/api/estado':self.respuesta(self.server.motor.estado())
            elif self.path=='/api/datos':self.respuesta(self.server.motor.datos())

            elif self.path == '/assets/logo-upn-150.png':
                imagen = Path(__file__).parent / 'assets' / 'logo-upn-150.png'
                if not imagen.is_file():
                    self.respuesta({'error': 'No se encontró el logo'}, 404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.end_headers()
                self.wfile.write(imagen.read_bytes())
                
            elif self.path=='/styles.css':
                self.send_response(200);self.send_header('Content-Type','text/css; charset=utf-8');self.end_headers()
                self.wfile.write(Path(__file__).with_name('styles.css').read_bytes())
            elif self.path in ('/','/datos'):
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
                self.wfile.write(Path(__file__).with_name('index.html' if self.path=='/' else 'datos.html').read_bytes())
            else:self.respuesta({'error':'Ruta inexistente'},404)
        except Exception:
            logging.exception('Error al consultar');self.respuesta({'error':'No se pudo consultar la base de datos.'},500)

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers.get('Host',''):raise ValueError('Origen no permitido')
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=4096:raise ValueError('Petición inválida')
            d=json.loads(self.rfile.read(n))
            if not isinstance(d,dict):raise ValueError('Se esperaba un objeto JSON')
            if self.path=='/api/recibir':
                r=self.server.motor.recibir(d['cuenta'],d['monto'],d['clave_peticion'],d.get('modo','normal'))
                mensaje=r['referencia']+(' agregada al final de la cola.' if r['nueva'] else ' ya estaba registrada; no se duplicó.')
            elif self.path=='/api/procesar':
                r=self.server.motor.procesar()
                mensaje=(r['referencia']+': '+r['detalle']) if r else 'La cola está vacía.'
            else:self.respuesta({'error':'Ruta inexistente'},404);return
            self.respuesta({'mensaje':mensaje,'resultado':r})
        except (ValueError,KeyError,TypeError) as e:self.respuesta({'error':str(e)},400)
        except Exception:
            logging.exception('Error de procesamiento')
            self.respuesta({'error':'No se confirmó el resultado. Revise los registros antes de continuar.'},500)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default=str(Path(__file__).with_name('transferencias.db')));p.add_argument('--port',type=int,default=8765)
    args=p.parse_args();server=HTTPServer(('127.0.0.1',args.port),Handler);server.motor=Motor(args.db)
    print(f'Abrir http://127.0.0.1:{args.port} | Base: {Path(args.db).resolve()}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.motor.db.close();server.server_close()
