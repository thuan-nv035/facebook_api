import uvicorn
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine
from routers import users, posts, comments, likes, follows, chat, notifications, friends, stories, reactions, search, \
    admin, calls, pin, archive, conversation_settings, group_invite, block

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Facebook Mini API")

app.include_router(users.router)
app.include_router(posts.router)
app.include_router(comments.router)
app.include_router(likes.router)
app.include_router(follows.router)
app.include_router(chat.router)
app.include_router(notifications.router)
app.include_router(friends.router)
app.include_router(stories.router)
app.include_router(reactions.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(calls.router)
app.include_router(pin.router)
app.include_router(archive.router)
app.include_router(conversation_settings.router)
app.include_router(group_invite.router)
app.include_router(block.router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
@app.get("/")
def root():
    return {
        "message": "Facebook Mini API is running"
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
