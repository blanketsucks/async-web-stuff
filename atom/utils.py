import traceback
from .response import Response, HTMLResponse, JSONResponse
import markdown as mark
import codecs
import json

__all__ = (
    'format_exception',
    'jsonify',
    'markdown',
    'render_html'
)


def format_exception(exc):
    server_exception_templ = """
    <div>
        <h1>500 Internal server error</h1>
        <span>Server got itself in trouble : <b>{exc}</b><span>
        <p>{traceback}</p>
    </div> 
    """

    resp = Response(status=500, content_type="text/html")
    trace = traceback.format_exc().replace("\n", "</br>")

    msg = server_exception_templ.format(exc=str(exc), traceback=trace)
    resp.add_body(msg)
    
    return resp

def jsonify(*, response=True, **kwargs):
    """Inspired by Flask's jsonify"""
    data = json.dumps(kwargs)

    if response:
        resp = JSONResponse(data)
        return resp

    return data

def markdown(fp: str):
    actual = fp + '.md'

    with open(actual, 'r') as file:
        content = file.read()
        resp = mark.markdown(content)

        return HTMLResponse(resp)
        
def render_html(fp: str):
    actual = fp + '.html'

    with codecs.open(actual, 'r') as file:
        resp = file.read()
        return HTMLResponse(resp)

