from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    password = Column(String(255))
    avatar = Column(String(255), nullable=True)
    bio = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship("Post", back_populates="owner")
    is_admin = Column(Integer, default=0)
    is_active = Column(Integer, default=1)

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    image = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post")
    likes = relationship("Like", back_populates="post")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="comments")


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))

    post = relationship("Post", back_populates="likes")

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="unique_user_post_like"),
    )


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id"))
    following_id = Column(Integer, ForeignKey("users.id"))

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="unique_follow"),
    )

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=True)
    image = Column(String(255), nullable=True)

    is_group = Column(Integer, default=0)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    status = Column(String(20), default="active")
    # active, request, rejected, deleted

    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))

    role = Column(String(20), default="member")
    # owner, admin, member

    joined_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=True)
    image = Column(String(255), nullable=True)
    is_seen = Column(Integer, default=0)

    file_url = Column(String(255), nullable=True)
    file_type = Column(String(50), nullable=True)

    is_recalled = Column(Integer, default=0)
    recalled_at = Column(DateTime, nullable=True)

    deleted_for_sender = Column(Integer, default=0)
    deleted_for_receiver = Column(Integer, default=0)
    reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

    is_edited = Column(Integer, default=0)
    edited_at = Column(DateTime, nullable=True)
    edit_count = Column(Integer, default=0)
    message_type = Column(String(30), default="text")
    call_status = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))      # người nhận thông báo
    actor_id = Column(Integer, ForeignKey("users.id"))     # người tạo hành động
    type = Column(String(50))                              # like, comment, follow, message
    message = Column(String(255))
    target_type = Column(String(50), nullable=True)        # post, user, conversation
    target_id = Column(Integer, nullable=True)
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class FriendRequest(Base):
    __tablename__ = "friend_requests"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime, default=datetime.utcnow)

class HiddenPost(Base):
    __tablename__ = "hidden_posts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))


class SavedPost(Base):
    __tablename__ = "saved_posts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))


class ReportPost(Base):
    __tablename__ = "report_posts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))
    reason = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Story(Base):
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=True)
    image = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expired_at = Column(DateTime)

class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    post_id = Column(Integer, ForeignKey("posts.id"))
    type = Column(String(20), default="like")  # like, love, haha, wow, sad, angry
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="unique_user_post_reaction"),
    )

class SearchHistory(Base):
    __tablename__ = "search_histories"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    keyword = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Call(Base):
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True)
    caller_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(Integer, nullable=True)

    call_type = Column(String(20))  # video / audio
    status = Column(String(20), default="missed")
    # pending, accepted, rejected, ended, missed

    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Integer, default=0)  # seconds

class BlockUser(Base):
    __tablename__ = "blocked_users"

    id = Column(Integer, primary_key=True, index=True)
    blocker_id = Column(Integer, ForeignKey("users.id"))
    blocked_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="unique_block_user"),
    )

class MutedConversation(Base):
    __tablename__ = "muted_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    muted_until = Column(DateTime, nullable=True)  # null = tắt vĩnh viễn
    created_at = Column(DateTime, default=datetime.utcnow)

class PinnedConversation(Base):
    __tablename__ = "pinned_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

class MessageReaction(Base):
    __tablename__ = "message_reactions"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    reaction_type = Column(String(20))  # like, love, haha, wow, sad, angry
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="unique_message_user_reaction"),
    )

class ConversationRead(Base):
    __tablename__ = "conversation_reads"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    last_read_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    read_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="unique_conversation_user_read"),
    )

class ArchivedConversation(Base):
    __tablename__ = "archived_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "conversation_id", name="unique_user_archived_conversation"),
    )

class GroupInviteLink(Base):
    __tablename__ = "group_invite_links"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), unique=True)
    invite_code = Column(String(100), unique=True, index=True)
    is_active = Column(Integer, default=1)
    require_approval = Column(Integer, default=1)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

class GroupJoinRequest(Base):
    __tablename__ = "group_join_requests"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    invite_code = Column(String(100))
    status = Column(String(20), default="pending")
    # pending, approved, rejected

    created_at = Column(DateTime, default=datetime.utcnow)
    handled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    handled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="unique_group_join_request"),
    )

class DeletedConversation(Base):
    __tablename__ = "deleted_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(Integer, ForeignKey("conversations.id"))

    # Xóa đến tin nhắn nào
    last_deleted_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

    deleted_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            name="unique_user_deleted_conversation"
        ),
    )