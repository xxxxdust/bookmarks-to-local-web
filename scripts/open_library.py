"""Check and serve an existing library on loopback. Close with Ctrl+C."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import webbrowser


def make_server(library,port):
    library=Path(library).resolve()
    if not (library/'阅读页.html').is_file():
        raise ValueError('No reading page here. Ask your assistant to generate the library first.')
    return ThreadingHTTPServer(('127.0.0.1',port),partial(SimpleHTTPRequestHandler,directory=str(library)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library',required=True,type=Path)
    p.add_argument('--port',type=int,default=8769)
    p.add_argument('--no-browser',action='store_true')
    a=p.parse_args()
    try: server=make_server(a.library,a.port)
    except (ValueError,OSError) as e:
        sys.exit('Cannot open library: '+str(e)+'\nIf the port is occupied, choose another --port; no existing service was stopped.')
    url='http://127.0.0.1:'+str(server.server_port)+'/阅读页.html'
    print('Reading page: '+url+'\nKeep this window open. Stop with Ctrl+C.',flush=True)
    if not a.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
