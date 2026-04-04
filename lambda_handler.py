import os
import sys
from mangum import Mangum
from app.main import app

# Handle both HTTP requests and EventBridge events
handler = Mangum(app, lifespan="auto")
