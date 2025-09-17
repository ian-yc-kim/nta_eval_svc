import logging

import uvicorn
from nta_eval_svc.app import app
from nta_eval_svc.config import SERVICE_PORT


# Set up logging for the application
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    service_port = int(SERVICE_PORT)
    uvicorn.run(app, host="0.0.0.0", port=service_port)


if __name__ == "__main__":
    # Entry point for the application
    main()