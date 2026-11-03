"""The language of a request's texts: its ``Accept-Language`` (AGI-6.4, AGI-9.2).

``LanguageMiddleware`` sets the language of the message catalog
(``archiwista.messages.language``) for the whole of a request, from the
``Accept-Language`` header: Polish when it prefers Polish, English otherwise
and without the header. Everything a route makes in that time renders its
texts in it (a route that is a plain function runs in a thread that copies
the context), so the texts of response models follow the request without
any route naming a language. A JSON answer under ``/api/v1``, and an event
stream, says which language it is in with ``Content-Language`` and that it
depends on the request with ``Vary: Accept-Language``; images, the OpenAPI
document (English always) and the interface's files hold no text in the
request's language and say neither. A problem names its own language
(``archiwista.api.errors.problem_response``), also when it is made outside
this middleware (the answer to an unexpected failure).
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from archiwista.api import API_PREFIX, OPENAPI_PATH
from archiwista.error_document import language_of
from archiwista.messages import language

# Content types of an answer that holds texts for a person.
_TEXT_ANSWERS = ("application/json", "application/problem+json", "text/event-stream")


class LanguageMiddleware:
    """Render the texts of each HTTP request in its ``Accept-Language``.

    Parameters
    ----------
    app : ASGIApp
        The wrapped application; put this middleware outermost, so that the
        rules of the others (``SecurityMiddleware``) answer in the language
        too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run an HTTP request in its language; other scopes pass unchanged."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        lang = language_of(Headers(scope=scope).get("accept-language"))
        path = str(scope["path"])
        api = path.startswith(f"{API_PREFIX}/") and path != OPENAPI_PATH

        async def send_in_language(message: Message) -> None:
            if api and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith(_TEXT_ANSWERS):
                    headers.setdefault("content-language", lang)
                    if "accept-language" not in headers.get("vary", "").lower():
                        headers.append("vary", "Accept-Language")
            await send(message)

        with language(lang):
            await self.app(scope, receive, send_in_language)
