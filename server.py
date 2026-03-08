import logging
import os

from uvicorn import Config, Server


LOG_LEVEL = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO"))


if __name__ == "__main__":
    uvicorn = Server(Config("app:api", host="0.0.0.0", port=5001, log_level=LOG_LEVEL))
    uvicorn.run()
