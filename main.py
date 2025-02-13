import os
import logging
from app import app

if __name__ == "__main__":
    # Configure detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting server on port {port}...")

    app.run(host='0.0.0.0', port=port, debug=True)