import os
import shutil
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import User, Conversation, ConversationMember, Message, Call, PinnedConversation, FriendRequest, \
    MessageReaction, ConversationRead, ArchivedConversation, DeletedConversation, BlockUser
from services.auth import get_current_user, is_blocked
from services.mute import is_conversation_muted
from websocket_manager import manager
from schemas.messages import ConversationCreate, MessageResponse, MessageReactionResponse, MessageReactionCreate, \
    MessageEdit

router = APIRouter(prefix="/api/v1", tags=["Chat"])
ALLOWED_MESSAGE_REACTIONS = ["like", "love", "haha", "wow", "sad", "angry"]

def format_duration(seconds: int):
    if not seconds:
        return "00:00"

    minutes = seconds // 60
    remain_seconds = seconds % 60

    return f"{minutes:02d}:{remain_seconds:02d}"

def create_call_message(db: Session, call: Call):
    call_label = "Cuộc gọi thoại" if call.call_type == "audio" else "Cuộc gọi video"

    if call.status == "ended":
        content = f"{call_label} · {format_duration(call.duration)}"
    elif call.status == "rejected":
        content = f"{call_label} bị từ chối"
    else:
        content = f"{call_label} nhỡ"

    msg = Message(
        conversation_id=call.conversation_id,
        sender_id=call.caller_id,
        content=content,
        message_type="call",
        call_status=call.status
    )

    db.add(msg)
    db.commit()
    db.refresh(msg)

    return msg

def are_friends(db: Session, user1_id: int, user2_id: int):
    return db.query(FriendRequest).filter(
        or_(
            and_(
                FriendRequest.sender_id == user1_id,
                FriendRequest.receiver_id == user2_id
            ),
            and_(
                FriendRequest.sender_id == user2_id,
                FriendRequest.receiver_id == user1_id
            )
        ),
        FriendRequest.status == "accepted"
    ).first() is not None

def is_member(db: Session, conversation_id: int, user_id: int):
    return db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first() is not None

def mark_conversation_read(
    db: Session,
    conversation_id: int,
    user_id: int,
    message_id: int | None = None
):
    read = db.query(ConversationRead).filter(
        ConversationRead.conversation_id == conversation_id,
        ConversationRead.user_id == user_id
    ).first()

    if read:
        read.last_read_message_id = message_id
        read.read_at = datetime.utcnow()
    else:
        read = ConversationRead(
            conversation_id=conversation_id,
            user_id=user_id,
            last_read_message_id=message_id,
            read_at=datetime.utcnow()
        )
        db.add(read)

    db.commit()
    return read

@router.websocket("/ws/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)

    await manager.send_to_user(user_id, {
        "type": "online",
        "user_id": user_id
    })

    try:
        while True:
            data = await websocket.receive_json()

            msg_type = data.get("type")

            db = SessionLocal()

            if msg_type == "message":
                conversation_id = data.get("conversation_id")
                content = data.get("content")
                reply_to_id = data.get("reply_to_id")
                conversation = db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()

                if not conversation:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Cuộc trò chuyện không tồn tại"
                    })
                    db.close()
                    continue

                if conversation.status == "rejected":
                    await websocket.send_json({
                        "type": "error",
                        "message": "Tin nhắn chờ đã bị từ chối"
                    })
                    db.close()
                    continue

                members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id
                ).all()

                member_ids = [m.user_id for m in members]

                if user_id not in member_ids:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn không thuộc cuộc trò chuyện này"
                    })
                    db.close()
                    continue

                if conversation.is_group == 0:
                    other_id = None

                    for member_id in member_ids:
                        if member_id != user_id:
                            other_id = member_id
                            break

                    if other_id and is_blocked(db, user_id, other_id):
                        await websocket.send_json({
                            "type": "error",
                            "message": "Không thể gửi tin nhắn vì đã bị chặn hoặc bạn đã chặn người này"
                        })
                        db.close()
                        continue

                reply_message = None

                if reply_to_id:
                    reply_message = db.query(Message).filter(
                        Message.id == reply_to_id,
                        Message.conversation_id == conversation_id
                    ).first()

                    if not reply_message:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Tin nhắn reply không tồn tại trong cuộc trò chuyện này"
                        })
                        db.close()
                        continue

                msg = Message(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    content=content,
                    reply_to_id=reply_to_id
                )

                db.add(msg)
                db.commit()
                db.refresh(msg)

                reply_payload = None

                if reply_message:
                    reply_payload = {
                        "id": reply_message.id,
                        "sender_id": reply_message.sender_id,
                        "content": "Tin nhắn đã được thu hồi" if reply_message.is_recalled == 1 else reply_message.content,
                        "file_url": None if reply_message.is_recalled == 1 else reply_message.file_url,
                        "file_type": None if reply_message.is_recalled == 1 else reply_message.file_type,
                        "is_recalled": reply_message.is_recalled
                    }

                payload = {
                    "type": "message",
                    "id": msg.id,
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "content": content,
                    "reply_to_id": reply_to_id,
                    "reply_to": reply_payload,
                    "message_type": msg.message_type,
                    "call_status": msg.call_status,
                    "is_edited": msg.is_edited,
                    "edited_at": msg.edited_at,
                    "edit_count": msg.edit_count,
                    "created_at": str(msg.created_at)
                }

                for member_id in member_ids:
                    await manager.send_to_user(member_id, payload)

                    if member_id != user_id:
                        if not is_conversation_muted(db, member_id, conversation_id):
                            await manager.send_to_user(member_id, {
                                "type": "notification",
                                "data": {
                                    "type": "message",
                                    "conversation_id": conversation_id,
                                    "sender_id": user_id,
                                    "message": content
                                }
                            })

                db.query(ArchivedConversation).filter(
                    ArchivedConversation.conversation_id == conversation_id,
                    ArchivedConversation.user_id != user_id
                ).delete(synchronize_session=False)

                db.commit()

            elif msg_type == "typing":
                conversation_id = data.get("conversation_id")

                if not is_member(db, conversation_id, user_id):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn không thuộc cuộc trò chuyện này"
                    })
                    db.close()
                    continue

                members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id
                ).all()

                member_ids = [m.user_id for m in members if m.user_id != user_id]

                await manager.send_to_many(member_ids, {
                    "type": "typing",
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "message": "đang nhập..."
                })

            elif msg_type == "seen":
                conversation_id = data.get("conversation_id")

                member = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.user_id == user_id
                ).first()

                if not member:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn không thuộc cuộc trò chuyện này"
                    })
                    db.close()
                    continue

                last_message = db.query(Message).filter(
                    Message.conversation_id == conversation_id
                ).order_by(Message.created_at.desc()).first()

                last_message_id = last_message.id if last_message else None

                mark_conversation_read(
                    db=db,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    message_id=last_message_id
                )

                db.query(Message).filter(
                    Message.conversation_id == conversation_id,
                    Message.sender_id != user_id
                ).update({
                    "is_seen": 1
                })

                db.commit()

                members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id
                ).all()

                member_ids = [m.user_id for m in members if m.user_id != user_id]

                await manager.send_to_many(member_ids, {
                    "type": "seen",
                    "conversation_id": conversation_id,
                    "seen_by": user_id,
                    "last_read_message_id": last_message_id,
                    "read_at": str(datetime.utcnow())
                })

            if msg_type == "call_request":
                receiver_id = data.get("receiver_id")

                if not manager.is_online(receiver_id):
                    await websocket.send_json({
                        "type": "call_failed",
                        "message": "Người dùng đang offline"
                    })
                    db.close()
                    continue

                call = Call(
                    caller_id=user_id,
                    receiver_id=receiver_id,
                    conversation_id=data.get("conversation_id"),
                    call_type=data.get("call_type", "video"),
                    status="pending"
                )

                db.add(call)
                db.commit()
                db.refresh(call)

                # Gửi call_id lại cho người gọi
                await websocket.send_json({
                    "type": "call_started",
                    "call_id": call.id,
                    "receiver_id": receiver_id,
                    "conversation_id": data.get("conversation_id"),
                    "call_type": data.get("call_type", "video")
                })

                # Gửi cuộc gọi đến cho người nhận
                await manager.send_to_user(receiver_id, {
                    "type": "incoming_call",
                    "call_id": call.id,
                    "caller_id": user_id,
                    "conversation_id": data.get("conversation_id"),
                    "call_type": data.get("call_type", "video")
                })



            elif msg_type == "call_accept":

                receiver_id = data.get("receiver_id")
                call_id = data.get("call_id")
                call = db.query(Call).filter(Call.id == call_id).first()

                if not call:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Cuộc gọi không tồn tại"
                    })
                    db.close()
                    continue

                call.status = "accepted"
                call.started_at = datetime.utcnow()
                db.commit()

                await manager.send_to_user(receiver_id, {
                    "type": "call_accepted",
                    "call_id": call.id,
                    "user_id": user_id,
                    "conversation_id": data.get("conversation_id")
                })



            elif msg_type == "call_reject":

                receiver_id = data.get("receiver_id")

                call_id = data.get("call_id")

                call = db.query(Call).filter(Call.id == call_id).first()

                if not call:
                    await websocket.send_json({

                        "type": "error",

                        "message": "Cuộc gọi không tồn tại"

                    })

                    db.close()

                    continue

                call.status = "rejected"

                call.ended_at = datetime.utcnow()

                db.commit()
                call_msg = create_call_message(db, call)

                await manager.send_to_user(receiver_id, {
                    "type": "call_rejected",
                    "call_id": call.id,
                    "user_id": user_id,
                    "conversation_id": data.get("conversation_id")
                })

                await manager.send_to_many([call.caller_id, call.receiver_id], {
                    "type": "message",
                    "id": call_msg.id,
                    "conversation_id": call.conversation_id,
                    "sender_id": call_msg.sender_id,
                    "content": call_msg.content,
                    "message_type": call_msg.message_type,
                    "call_status": call_msg.call_status,
                    "created_at": str(call_msg.created_at)
                })


            elif msg_type == "call_end":

                call_id = data.get("call_id")

                receiver_id = data.get("receiver_id")

                call = db.query(Call).filter(Call.id == call_id).first()

                if not call:
                    await websocket.send_json({

                        "type": "error",

                        "message": "Cuộc gọi không tồn tại"

                    })

                    db.close()

                    continue

                call.ended_at = datetime.utcnow()

                if call.status == "accepted":
                    call.status = "ended"
                    if call.started_at:
                        call.duration = int(
                            (call.ended_at - call.started_at).total_seconds()
                        )
                else:
                    call.status = "missed"
                    call.duration = 0

                db.commit()
                db.refresh(call)
                call_msg = create_call_message(db, call)

                await manager.send_to_user(receiver_id, {
                    "type": "call_ended",
                    "call_id": call.id,
                    "user_id": user_id,
                    "conversation_id": call.conversation_id,
                    "duration": call.duration,
                    "status": call.status
                })

                await manager.send_to_many([call.caller_id, call.receiver_id], {
                    "type": "message",
                    "id": call_msg.id,
                    "conversation_id": call.conversation_id,
                    "sender_id": call_msg.sender_id,
                    "content": call_msg.content,
                    "message_type": call_msg.message_type,
                    "call_status": call_msg.call_status,
                    "created_at": str(call_msg.created_at)
                })

            elif msg_type == "webrtc_offer":
                receiver_id = data.get("receiver_id")

                await manager.send_to_user(receiver_id, {
                    "type": "webrtc_offer",
                    "sender_id": user_id,
                    "conversation_id": data.get("conversation_id"),
                    "offer": data.get("offer")
                })


            elif msg_type == "webrtc_answer":
                receiver_id = data.get("receiver_id")

                await manager.send_to_user(receiver_id, {
                    "type": "webrtc_answer",
                    "sender_id": user_id,
                    "conversation_id": data.get("conversation_id"),
                    "answer": data.get("answer")
                })


            elif msg_type == "ice_candidate":
                receiver_id = data.get("receiver_id")

                await manager.send_to_user(receiver_id, {
                    "type": "ice_candidate",
                    "sender_id": user_id,
                    "conversation_id": data.get("conversation_id"),
                    "candidate": data.get("candidate")
                })


            elif msg_type == "file":

                conversation_id = data.get("conversation_id")
                file_url = data.get("file_url")
                file_type = data.get("file_type")
                reply_to_id = data.get("reply_to_id")

                conversation = db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()

                if not conversation:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Cuộc trò chuyện không tồn tại"
                    })

                    db.close()
                    continue

                if conversation.status == "rejected":
                    await websocket.send_json({
                        "type": "error",
                        "message": "Tin nhắn chờ đã bị từ chối"
                    })

                    db.close()
                    continue

                members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == conversation_id
                ).all()

                member_ids = [m.user_id for m in members]
                if user_id not in member_ids:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn không thuộc cuộc trò chuyện này"
                    })

                    db.close()
                    continue

                blocked = any(
                    is_blocked(db, user_id, member_id)
                    for member_id in member_ids
                    if member_id != user_id
                )

                if blocked:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn không thể gửi file vì đã bị block"
                    })

                    db.close()
                    continue

                reply_message = None

                if reply_to_id:
                    reply_message = db.query(Message).filter(
                        Message.id == reply_to_id,
                        Message.conversation_id == conversation_id
                    ).first()

                    if not reply_message:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Tin nhắn reply không tồn tại"
                        })

                        db.close()
                        continue

                msg = Message(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    file_url=file_url,
                    file_type=file_type,
                    reply_to_id=reply_to_id,
                    message_type="file"
                )

                db.add(msg)
                db.commit()
                db.refresh(msg)

                reply_payload = None

                if reply_message:
                    reply_payload = {
                        "id": reply_message.id,
                        "sender_id": reply_message.sender_id,
                        "content": "Tin nhắn đã được thu hồi" if reply_message.is_recalled == 1 else reply_message.content,
                        "file_url": None if reply_message.is_recalled == 1 else reply_message.file_url,
                        "file_type": None if reply_message.is_recalled == 1 else reply_message.file_type,
                        "is_recalled": reply_message.is_recalled
                    }

                payload = {
                    "type": "file",
                    "id": msg.id,
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "file_url": file_url,
                    "file_type": file_type,
                    "reply_to_id": reply_to_id,
                    "reply_to": reply_payload,
                    "is_recalled": msg.is_recalled,
                    "is_edited": msg.is_edited,
                    "edited_at": msg.edited_at,
                    "edit_count": msg.edit_count,
                    "message_type": msg.message_type,
                    "call_status": msg.call_status,
                    "created_at": str(msg.created_at),
                }

                await manager.send_to_many(member_ids, payload)

                db.query(ArchivedConversation).filter(
                    ArchivedConversation.conversation_id == conversation_id,
                    ArchivedConversation.user_id != user_id
                ).delete(synchronize_session=False)

                db.commit()

            elif msg_type == "recall_message":
                message_id = data.get("message_id")

                msg = db.query(Message).filter(Message.id == message_id).first()

                if not msg:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Tin nhắn không tồn tại"
                    })
                    db.close()
                    continue

                if msg.sender_id != user_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Bạn chỉ được thu hồi tin nhắn của mình"
                    })
                    db.close()
                    continue

                msg.content = None
                msg.file_url = None
                msg.file_type = None
                msg.image = None
                msg.is_recalled = 1
                msg.recalled_at = datetime.utcnow()

                db.commit()

                members = db.query(ConversationMember).filter(
                    ConversationMember.conversation_id == msg.conversation_id
                ).all()

                member_ids = [m.user_id for m in members]

                await manager.send_to_many(member_ids, {
                    "type": "message_recalled",
                    "message_id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "recalled_by": user_id,
                    "message": "Tin nhắn đã được thu hồi"
                })

            db.close()

    except WebSocketDisconnect:
        manager.disconnect(user_id)


@router.post("/conversations")
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member_ids = list(set(data.member_ids + [current_user.id]))

    # Không cho tạo chat cá nhân với nhiều hơn 1 người
    if not data.is_group and len(member_ids) != 2:
        raise HTTPException(400, "Chat cá nhân chỉ gồm 2 người")

    # Nếu là chat cá nhân 1-1 thì kiểm tra đã tồn tại chưa
    if not data.is_group and len(member_ids) == 2:
        other_id = [uid for uid in member_ids if uid != current_user.id][0]

        my_conversation_ids = db.query(ConversationMember.conversation_id).filter(
            ConversationMember.user_id == current_user.id
        ).all()

        my_ids = [item[0] for item in my_conversation_ids]

        other_conversation_ids = db.query(ConversationMember.conversation_id).filter(
            ConversationMember.user_id == other_id
        ).all()

        other_ids = [item[0] for item in other_conversation_ids]

        common_ids = list(set(my_ids) & set(other_ids))

        existing_conversation = db.query(Conversation).filter(
            Conversation.id.in_(common_ids),
            Conversation.is_group == 0,
            Conversation.status != "deleted"
        ).first()

        if existing_conversation:
            # Nếu user hiện tại từng xóa cuộc trò chuyện này,
            # khi tạo lại thì khôi phục cho riêng user đó
            deleted = db.query(DeletedConversation).filter(
                DeletedConversation.user_id == current_user.id,
                DeletedConversation.conversation_id == existing_conversation.id
            ).first()

            if deleted:
                db.delete(deleted)

            # Nếu conversation từng bị archive thì cũng bỏ archive
            archived = db.query(ArchivedConversation).filter(
                ArchivedConversation.user_id == current_user.id,
                ArchivedConversation.conversation_id == existing_conversation.id
            ).first()

            if archived:
                db.delete(archived)

            db.commit()

            return {
                "message": "Cuộc trò chuyện đã tồn tại, đã khôi phục lại",
                "conversation_id": existing_conversation.id,
                "member_ids": member_ids
            }
    status = "active"

    conversation = Conversation(
        name=data.name if data.is_group else None,
        is_group=1 if data.is_group else 0,
        creator_id=current_user.id,
        status=status
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    for user_id in member_ids:
        role = "owner" if user_id == current_user.id else "member"

        db.add(ConversationMember(
            conversation_id=conversation.id,
            user_id=user_id,
            role=role
        ))

    db.commit()

    return {
        "message": "Tạo cuộc trò chuyện thành công",
        "conversation_id": conversation.id,
        "member_ids": member_ids
    }


@router.get("/conversations")
def get_my_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    my_conversation_ids = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id == current_user.id
    ).all()

    ids = [item[0] for item in my_conversation_ids]

    deleted_rows = db.query(DeletedConversation).filter(
        DeletedConversation.user_id == current_user.id
    ).all()

    deleted_map = {
        d.conversation_id: d.last_deleted_message_id
        for d in deleted_rows
    }

    archived = db.query(ArchivedConversation.conversation_id).filter(
        ArchivedConversation.user_id == current_user.id
    ).all()

    archived_ids = [a[0] for a in archived]

    pinned = db.query(PinnedConversation.conversation_id).filter(
        PinnedConversation.user_id == current_user.id
    ).all()

    pinned_ids = [p[0] for p in pinned]

    conversations = db.query(Conversation).filter(
        Conversation.id.in_(ids),
        Conversation.status.in_(['active','request']),
        ~Conversation.id.in_(archived_ids)
    ).all()

    result = []

    for c in conversations:

        blocked_rows = db.query(BlockUser.blocked_id).filter(
            BlockUser.blocker_id == current_user.id
        ).all()

        blocked_user_ids = [item[0] for item in blocked_rows]

        members = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == c.id
        ).all()

        member_ids = [m.user_id for m in members]

        users = db.query(User).filter(
            User.id.in_(member_ids)
        ).all()

        if c.is_group == 0:
            other_user_id = None

            for uid in member_ids:
                if uid != current_user.id:
                    other_user_id = uid
                    break

            if other_user_id in blocked_user_ids:
                continue

        user_map = {u.id: u for u in users}

        display_name = c.name
        display_avatar = None

        if c.is_group == 1:
            display_name = c.name or f"Nhóm #{c.id}"
        else:
            other_user = None

            for u in users:
                if u.id != current_user.id:
                    other_user = u
                    break

            if other_user:
                display_name = other_user.full_name
                display_avatar = other_user.avatar
            else:
                display_name = f"Cuộc trò chuyện #{c.id}"

        last_message = db.query(Message).filter(
            Message.conversation_id == c.id
        ).order_by(Message.created_at.desc()).first()

        deleted_until_id = deleted_map.get(c.id)

        if deleted_until_id:
            # Nếu chưa có tin mới hơn tin đã xóa thì không hiện conversation
            if not last_message or last_message.id <= deleted_until_id:
                continue

        read = db.query(ConversationRead).filter(
            ConversationRead.conversation_id == c.id,
            ConversationRead.user_id == current_user.id
        ).first()

        unread_query = db.query(Message).filter(
            Message.conversation_id == c.id,
            Message.sender_id != current_user.id,
            Message.is_recalled == 0
        )

        if read and read.last_read_message_id:
            unread_query = unread_query.filter(
                Message.id > read.last_read_message_id
            )

        unread_count = unread_query.count()

        last_message_payload = None

        if last_message:
            if last_message.is_recalled == 1:
                last_message_text = "Tin nhắn đã được thu hồi"
            elif last_message.content:
                last_message_text = last_message.content
            elif last_message.file_type == "image":
                last_message_text = "Đã gửi một hình ảnh"
            elif last_message.file_type == "video":
                last_message_text = "Đã gửi một video"
            elif last_message.file_type == "audio":
                last_message_text = "Đã gửi một âm thanh"
            elif last_message.file_url:
                last_message_text = "Đã gửi một tệp"
            else:
                last_message_text = ""

            last_message_payload = {
                "id": last_message.id,
                "sender_id": last_message.sender_id,
                "content": last_message_text,
                "created_at": last_message.created_at
            }
        
        check_is_online = None
        
        if c.is_group == 0:
            other_user_id = None

            for uid in member_ids:
                if uid != current_user.id:
                    check_is_online = manager.is_online(uid)
                    break
        else:
            check_is_online = True

        result.append({
            "id": c.id,
            "name": c.name,
            "display_name": display_name,
            "display_avatar": display_avatar,
            "is_group": c.is_group,
            "is_pinned": c.id in pinned_ids,
            "is_online": check_is_online,
            "unread_count": unread_count,
            "last_message": last_message_payload,
            "created_at": c.created_at,
            "members": [
                {
                    "id": u.id,
                    "full_name": u.full_name,
                    "avatar": u.avatar
                }
                for u in users
            ]
        })

    result = sorted(
        result,
        key=lambda x: (
            not x["is_pinned"],
            -(x["last_message"]["created_at"].timestamp() if x["last_message"] else x["created_at"].timestamp())
        )
    )

    return result

@router.delete("/conversations/{conversation_id}/delete-for-me")
def delete_conversation_for_me(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    last_message = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.id.desc()).first()

    last_message_id = last_message.id if last_message else None

    deleted = db.query(DeletedConversation).filter(
        DeletedConversation.user_id == current_user.id,
        DeletedConversation.conversation_id == conversation_id
    ).first()

    if deleted:
        deleted.last_deleted_message_id = last_message_id
        deleted.deleted_at = datetime.utcnow()
    else:
        deleted = DeletedConversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
            last_deleted_message_id=last_message_id
        )
        db.add(deleted)

    db.commit()

    return {
        "message": "Đã xóa cuộc trò chuyện phía bạn",
        "conversation_id": conversation_id,
        "last_deleted_message_id": last_message_id
    }

@router.get("/conversations/search")
def search_conversations(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    keyword = f"%{q}%"

    my_conversation_ids = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id == current_user.id
    ).all()

    ids = [item[0] for item in my_conversation_ids]

    conversations = db.query(Conversation).filter(
        Conversation.id.in_(ids),
        Conversation.status == "active"
    ).all()

    result = []

    for c in conversations:
        members = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == c.id
        ).all()

        member_ids = [m.user_id for m in members]

        users = db.query(User).filter(
            User.id.in_(member_ids)
        ).all()

        matched_by_group_name = False

        if c.name and q.lower() in c.name.lower():
            matched_by_group_name = True

        matched_users = []

        for u in users:
            if q.lower() in u.full_name.lower():
                matched_users.append({
                    "id": u.id,
                    "full_name": u.full_name,
                    "avatar": u.avatar
                })

        if matched_by_group_name or len(matched_users) > 0:
            result.append({
                "id": c.id,
                "name": c.name,
                "is_group": c.is_group,
                "matched_by_group_name": matched_by_group_name,
                "matched_users": matched_users,
                "created_at": c.created_at
            })

    return {
        "keyword": q,
        "total": len(result),
        "conversations": result
    }

@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    limit: int = Query(20, ge=1, le=100),
    before_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(
            status_code=403,
            detail="Bạn không thuộc cuộc trò chuyện này"
        )

    deleted = db.query(DeletedConversation).filter(
        DeletedConversation.user_id == current_user.id,
        DeletedConversation.conversation_id == conversation_id
    ).first()

    query = db.query(Message).filter(
        Message.conversation_id == conversation_id
    )

    if deleted and deleted.last_deleted_message_id:
        query = query.filter(
            Message.id > deleted.last_deleted_message_id
        )

    if before_id:
        query = query.filter(Message.id < before_id)

    messages = query.order_by(
        Message.id.desc()
    ).limit(limit).all()

    messages = list(reversed(messages))

    result = []

    for msg in messages:
        if msg.sender_id == current_user.id and msg.deleted_for_sender == 1:
            continue

        if msg.sender_id != current_user.id and msg.deleted_for_receiver == 1:
            continue

        reply_payload = None

        if msg.reply_to_id:
            reply_msg = db.query(Message).filter(
                Message.id == msg.reply_to_id
            ).first()

            if reply_msg:
                reply_payload = {
                    "id": reply_msg.id,
                    "sender_id": reply_msg.sender_id,
                    "content": "Tin nhắn đã được thu hồi" if reply_msg.is_recalled == 1 else reply_msg.content,
                    "file_url": None if reply_msg.is_recalled == 1 else reply_msg.file_url,
                    "file_type": None if reply_msg.is_recalled == 1 else reply_msg.file_type,
                    "is_recalled": reply_msg.is_recalled
                }

        reactions = db.query(MessageReaction).filter(
            MessageReaction.message_id == msg.id
        ).all()

        reaction_summary = {
            "like": 0,
            "love": 0,
            "haha": 0,
            "wow": 0,
            "sad": 0,
            "angry": 0
        }

        reaction_users = []

        for r in reactions:
            reaction_summary[r.reaction_type] += 1
            reaction_users.append({
                "user_id": r.user_id,
                "reaction_type": r.reaction_type
            })

        if msg.is_recalled == 1:
            content = "Tin nhắn đã được thu hồi"
            file_url = None
            file_type = None
        else:
            content = msg.content
            file_url = msg.file_url
            file_type = msg.file_type

        result.append({
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_id": msg.sender_id,
            "content": content,
            "file_url": file_url,
            "file_type": file_type,
            "is_recalled": msg.is_recalled,
            "reply_to_id": msg.reply_to_id,
            "reply_to": reply_payload,
            "is_edited": msg.is_edited,
            "edited_at": msg.edited_at,
            "edit_count": msg.edit_count,
            "message_type": msg.message_type,
            "call_status": msg.call_status,
            "reactions": {
                "total": len(reactions),
                "summary": reaction_summary,
                "users": reaction_users
            },
            "created_at": msg.created_at
        })

    if result:
        last_message_id = result[-1]["id"]

        mark_conversation_read(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
            message_id=last_message_id
        )

    return {
        "messages": result,
        "has_more": len(messages) == limit,
        "oldest_id": result[0]["id"] if result else None
    }

@router.get("/conversations/{conversation_id}/search-messages")
def search_messages_in_conversation(
    conversation_id: int,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Kiểm tra user có thuộc cuộc trò chuyện không
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    keyword = f"%{q}%"

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.content.ilike(keyword),
        Message.is_recalled == 0
    ).order_by(Message.created_at.desc()).all()

    result = []

    for msg in messages:
        # Nếu user đã xóa tin nhắn phía mình thì không hiện trong search
        if msg.sender_id == current_user.id and msg.deleted_for_sender == 1:
            continue

        if msg.sender_id != current_user.id and msg.deleted_for_receiver == 1:
            continue

        result.append({
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_id": msg.sender_id,
            "content": msg.content,
            "file_url": msg.file_url,
            "file_type": msg.file_type,
            "reply_to_id": msg.reply_to_id,
            "created_at": msg.created_at
        })

    return {
        "keyword": q,
        "total": len(result),
        "limit": limit,
        "offset": offset,
        "messages": result
    }

@router.patch("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    last_message = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.desc()).first()

    last_message_id = last_message.id if last_message else None

    mark_conversation_read(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        message_id=last_message_id
    )

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id
    ).all()

    member_ids = [m.user_id for m in members if m.user_id != current_user.id]

    await manager.send_to_many(member_ids, {
        "type": "conversation_read",
        "conversation_id": conversation_id,
        "user_id": current_user.id,
        "last_read_message_id": last_message_id,
        "read_at": str(datetime.utcnow())
    })

    return {
        "message": "Đã đánh dấu đã đọc",
        "conversation_id": conversation_id,
        "last_read_message_id": last_message_id
    }

@router.get("/conversations/{conversation_id}/unread-count")
def get_unread_count(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    read = db.query(ConversationRead).filter(
        ConversationRead.conversation_id == conversation_id,
        ConversationRead.user_id == current_user.id
    ).first()

    query = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sender_id != current_user.id,
        Message.is_recalled == 0
    )

    if read and read.last_read_message_id:
        query = query.filter(Message.id > read.last_read_message_id)

    count = query.count()

    return {
        "conversation_id": conversation_id,
        "unread_count": count
    }

@router.get("/users/{user_id}/online")
def check_online(user_id: int):
    return {
        "user_id": user_id,
        "online": manager.is_online(user_id)
    }

@router.get("/message-requests")
def get_message_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    my_conversation_ids = db.query(ConversationMember.conversation_id).filter(
        ConversationMember.user_id == current_user.id
    ).all()

    ids = [item[0] for item in my_conversation_ids]

    requests = db.query(Conversation).filter(
        Conversation.id.in_(ids),
        Conversation.status == "request"
    ).order_by(Conversation.created_at.desc()).all()

    return requests

@router.patch("/message-requests/{conversation_id}/accept")
def accept_message_request(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.status == "request"
    ).first()

    if not conversation:
        raise HTTPException(404, "Không tìm thấy tin nhắn chờ")

    conversation.status = "active"
    db.commit()

    return {"message": "Đã chấp nhận tin nhắn chờ"}

@router.patch("/message-requests/{conversation_id}/reject")
def reject_message_request(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.status == "request"
    ).first()

    if not conversation:
        raise HTTPException(404, "Không tìm thấy tin nhắn chờ")

    conversation.status = "rejected"
    db.commit()

    return {"message": "Đã từ chối tin nhắn chờ"}

@router.post("/upload")
def upload_chat_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    allowed_types = [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",

        "video/mp4",

        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/ogg",
        "audio/mp4",

        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/x-rar-compressed",
        "application/octet-stream",
    ]

    if file.content_type not in allowed_types:
        raise HTTPException(400, "File không hợp lệ")

    os.makedirs("uploads/chat", exist_ok=True)

    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    filename = f"{uuid4()}.{ext}"
    file_path = f"uploads/chat/{filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    content_type = file.content_type or ""

    if "image" in content_type:
        file_type = "image"
    elif "video" in content_type:
        file_type = "video"
    elif "audio" in content_type:
        file_type = "audio"
    else:
        file_type = "file"

    return {
        "file_url": f"/uploads/chat/{filename}",
        "file_type": file_type,
        "file_name": file.filename
    }

@router.patch("/messages/{message_id}/recall")
async def recall_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    if msg.sender_id != current_user.id:
        raise HTTPException(403, "Bạn chỉ được thu hồi tin nhắn của mình")

    if msg.is_recalled == 1:
        return {"message": "Tin nhắn đã được thu hồi trước đó"}

    msg.content = None
    msg.file_url = None
    msg.file_type = None
    msg.image = None
    msg.is_recalled = 1
    msg.recalled_at = datetime.utcnow()

    db.commit()
    db.refresh(msg)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "message_recalled",
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "recalled_by": current_user.id,
        "message": "Tin nhắn đã được thu hồi"
    })

    return {"message": "Đã thu hồi tin nhắn"}

@router.delete("/messages/{message_id}/delete-for-me")
def delete_message_for_me(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    if msg.sender_id == current_user.id:
        msg.deleted_for_sender = 1
    else:
        msg.deleted_for_receiver = 1

    db.commit()

    return {"message": "Đã xóa tin nhắn phía bạn"}

@router.post("/messages/{message_id}/reactions", response_model=MessageReactionResponse)
async def react_message(
    message_id: int,
    data: MessageReactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if data.reaction_type not in ALLOWED_MESSAGE_REACTIONS:
        raise HTTPException(400, "Reaction không hợp lệ")

    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    if msg.is_recalled == 1:
        raise HTTPException(400, "Không thể react tin nhắn đã thu hồi")

    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    existing = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == current_user.id
    ).first()

    if existing:
        existing.reaction_type = data.reaction_type
        db.commit()
        db.refresh(existing)
        reaction = existing
    else:
        reaction = MessageReaction(
            message_id=message_id,
            user_id=current_user.id,
            reaction_type=data.reaction_type
        )

        db.add(reaction)
        db.commit()
        db.refresh(reaction)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "message_reaction",
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "user_id": current_user.id,
        "reaction_type": reaction.reaction_type
    })

    return reaction

@router.delete("/messages/{message_id}/reactions")
async def remove_message_reaction(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    reaction = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id,
        MessageReaction.user_id == current_user.id
    ).first()

    if not reaction:
        return {"message": "Bạn chưa react tin nhắn này"}

    db.delete(reaction)
    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "message_reaction_removed",
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "user_id": current_user.id
    })

    return {"message": "Đã bỏ reaction"}

@router.get("/messages/{message_id}/reactions")
def get_message_reactions(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    reactions = db.query(MessageReaction).filter(
        MessageReaction.message_id == message_id
    ).all()

    summary = {
        "like": 0,
        "love": 0,
        "haha": 0,
        "wow": 0,
        "sad": 0,
        "angry": 0
    }

    users = []

    for r in reactions:
        summary[r.reaction_type] += 1
        users.append({
            "user_id": r.user_id,
            "reaction_type": r.reaction_type
        })

    return {
        "message_id": message_id,
        "total": len(reactions),
        "summary": summary,
        "users": users
    }

@router.patch("/messages/{message_id}/edit")
async def edit_message(
    message_id: int,
    data: MessageEdit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    msg = db.query(Message).filter(Message.id == message_id).first()

    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    if msg.sender_id != current_user.id:
        raise HTTPException(403, "Bạn chỉ được sửa tin nhắn của mình")

    if msg.is_recalled == 1:
        raise HTTPException(400, "Không thể sửa tin nhắn đã thu hồi")

    if msg.file_url:
        raise HTTPException(400, "Không thể sửa tin nhắn file/ảnh/video")

    if not msg.content:
        raise HTTPException(400, "Tin nhắn không có nội dung để sửa")

    time_limit = msg.created_at + timedelta(minutes=15)

    if datetime.utcnow() > time_limit:
        raise HTTPException(400, "Đã quá thời gian cho phép sửa tin nhắn")

    if not data.content.strip():
        raise HTTPException(400, "Nội dung không được để trống")

    msg.content = data.content.strip()
    msg.is_edited = 1
    msg.edited_at = datetime.utcnow()
    msg.edit_count = (msg.edit_count or 0) + 1

    db.commit()
    db.refresh(msg)

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == msg.conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "message_edited",
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_id": msg.sender_id,
        "content": msg.content,
        "is_edited": msg.is_edited,
        "edited_at": str(msg.edited_at)
    })

    return {
        "message": "Đã sửa tin nhắn",
        "data": {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_id": msg.sender_id,
            "content": msg.content,
            "is_edited": msg.is_edited,
            "edited_at": msg.edited_at,
            "edit_count": msg.edit_count
        }
    }

@router.get("/conversations/{conversation_id}/media")
def get_conversation_media(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == current_user.id
    ).first()

    if not member:
        raise HTTPException(403, "Bạn không thuộc cuộc trò chuyện này")

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.file_url.isnot(None),
        Message.is_recalled == 0
    ).order_by(Message.created_at.desc()).all()

    result = []

    for msg in messages:
        if msg.sender_id == current_user.id and msg.deleted_for_sender == 1:
            continue

        if msg.sender_id != current_user.id and msg.deleted_for_receiver == 1:
            continue

        result.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "file_url": msg.file_url,
            "file_type": msg.file_type,
            "created_at": msg.created_at
        })

    return result
