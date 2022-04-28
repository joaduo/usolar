import uvicorn
import typing
import jinja2

from os import PathLike
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


class Jinja2TemplatesCustom(Jinja2Templates):
    def _create_env(
        self, directory: typing.Union[str, PathLike]
    ) -> "jinja2.Environment":
        @jinja2.pass_context
        def url_for(context: dict, name: str, **path_params: typing.Any) -> str:
            request = context["request"]
            return request.url_for(name, **path_params)

        loader = jinja2.FileSystemLoader(directory)
        env = jinja2.Environment(loader=loader,
                                 autoescape=True,
                                 variable_start_string='@=',
                                 variable_end_string='=@')
        env.globals["url_for"] = url_for
        return env

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2TemplatesCustom(directory="")

origins = [
    "http://localhost",
    "http://localhost:8080",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse("client.html", {"request":request, "SERVER_ADDRESS": "http://192.168.4.1"})


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)
