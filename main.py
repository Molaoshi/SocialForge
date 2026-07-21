from fastapi import FastAPI

app = FastAPI(title='SocialForge')

@app.get('/')
def root():
    return {'message': 'SocialForge is running!'}