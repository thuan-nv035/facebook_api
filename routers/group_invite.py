from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4

from database import get_db
from models import User, Conversation, ConversationMember, GroupInviteLink, GroupJoinRequest
from services.auth import get_current_user
from websocket_manager import manager
from schemas.messages import JoinByInviteRequest

router = APIRouter(prefix="/api/v1/group-invites", tags=["Group Invites"])

def get_conversation_or_404(db: Session, conversation_id: int):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(404, "Cuộc trò chuyện không tồn tại")

    if conversation.status == "deleted":
        raise HTTPException(404, "Nhóm đã bị xóa")

    if conversation.is_group != 1:
        raise HTTPException(400, "Chỉ nhóm mới có link mời")

    return conversation


def get_member(db: Session, conversation_id: int, user_id: int):
    return db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id == user_id
    ).first()


def check_admin_or_owner(db: Session, conversation_id: int, user_id: int):
    member = get_member(db, conversation_id, user_id)

    if not member:
        raise HTTPException(403, "Bạn không thuộc nhóm này")

    if member.role not in ["owner", "admin"]:
        raise HTTPException(403, "Chỉ trưởng nhóm hoặc admin mới có quyền")

    return member


def generate_invite_code():
    return uuid4().hex[:16]

@router.post("/conversations/{conversation_id}")
def create_or_get_invite_link(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.conversation_id == conversation_id
    ).first()

    if invite:
        return {
            "message": "Link mời đã tồn tại",
            "conversation_id": conversation_id,
            "invite_code": invite.invite_code,
            "is_active": invite.is_active,
            "invite_url": f"/join-group/{invite.invite_code}"
        }

    invite = GroupInviteLink(
        conversation_id=conversation_id,
        invite_code=generate_invite_code(),
        is_active=1,
        created_by=current_user.id
    )

    db.add(invite)
    db.commit()
    db.refresh(invite)

    return {
        "message": "Đã tạo link mời nhóm",
        "conversation_id": conversation_id,
        "invite_code": invite.invite_code,
        "is_active": invite.is_active,
        "invite_url": f"/join-group/{invite.invite_code}"
    }

@router.patch("/conversations/{conversation_id}/enable")
def enable_invite_link(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.conversation_id == conversation_id
    ).first()

    if not invite:
        raise HTTPException(404, "Chưa có link mời")

    invite.is_active = 1
    db.commit()

    return {"message": "Đã bật link mời"}

@router.patch("/conversations/{conversation_id}/disable")
def disable_invite_link(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.conversation_id == conversation_id
    ).first()

    if not invite:
        raise HTTPException(404, "Chưa có link mời")

    invite.is_active = 0
    db.commit()

    return {"message": "Đã tắt link mời"}

@router.patch("/conversations/{conversation_id}/reset")
def reset_invite_link(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.conversation_id == conversation_id
    ).first()

    if not invite:
        invite = GroupInviteLink(
            conversation_id=conversation_id,
            invite_code=generate_invite_code(),
            is_active=1,
            created_by=current_user.id
        )
        db.add(invite)
    else:
        invite.invite_code = generate_invite_code()
        invite.is_active = 1
        invite.created_by = current_user.id

    db.commit()
    db.refresh(invite)

    return {
        "message": "Đã reset link mời",
        "invite_code": invite.invite_code,
        "invite_url": f"/join-group/{invite.invite_code}"
    }

@router.post("/join")
async def join_group_by_invite(
    data: JoinByInviteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.invite_code == data.invite_code
    ).first()

    if not invite:
        raise HTTPException(404, "Link mời không tồn tại")

    if invite.is_active != 1:
        raise HTTPException(400, "Link mời đã bị tắt")

    conversation = db.query(Conversation).filter(
        Conversation.id == invite.conversation_id
    ).first()

    if not conversation or conversation.status == "deleted":
        raise HTTPException(404, "Nhóm không tồn tại")

    if conversation.is_group != 1:
        raise HTTPException(400, "Đây không phải nhóm")

    existing_member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation.id,
        ConversationMember.user_id == current_user.id
    ).first()

    if existing_member:
        return {
            "message": "Bạn đã ở trong nhóm này",
            "conversation_id": conversation.id
        }

    # Nếu nhóm không cần duyệt thì cho vào thẳng
    if invite.require_approval == 0:
        member = ConversationMember(
            conversation_id=conversation.id,
            user_id=current_user.id,
            role="member"
        )

        db.add(member)
        db.commit()

        members = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation.id
        ).all()

        member_ids = [m.user_id for m in members]

        await manager.send_to_many(member_ids, {
            "type": "group_member_joined_by_invite",
            "conversation_id": conversation.id,
            "user_id": current_user.id
        })

        return {
            "message": "Đã tham gia nhóm",
            "conversation_id": conversation.id,
            "group_name": conversation.name
        }

    # Nếu cần duyệt thì tạo request
    existing_request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.conversation_id == conversation.id,
        GroupJoinRequest.user_id == current_user.id
    ).first()

    if existing_request:
        if existing_request.status == "pending":
            return {
                "message": "Bạn đã gửi yêu cầu tham gia, đang chờ duyệt",
                "request_id": existing_request.id,
                "status": existing_request.status
            }

        if existing_request.status == "rejected":
            existing_request.status = "pending"
            existing_request.invite_code = data.invite_code
            existing_request.created_at = datetime.utcnow()
            existing_request.handled_by = None
            existing_request.handled_at = None

            db.commit()
            db.refresh(existing_request)

            return {
                "message": "Đã gửi lại yêu cầu tham gia nhóm",
                "request_id": existing_request.id,
                "status": existing_request.status
            }

        if existing_request.status == "approved":
            return {
                "message": "Yêu cầu của bạn đã được duyệt trước đó"
            }

    join_request = GroupJoinRequest(
        conversation_id=conversation.id,
        user_id=current_user.id,
        invite_code=data.invite_code,
        status="pending"
    )

    db.add(join_request)
    db.commit()
    db.refresh(join_request)

    admins = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation.id,
        ConversationMember.role.in_(["owner", "admin"])
    ).all()

    admin_ids = [a.user_id for a in admins]

    await manager.send_to_many(admin_ids, {
        "type": "group_join_request",
        "conversation_id": conversation.id,
        "request_id": join_request.id,
        "user_id": current_user.id
    })

    return {
        "message": "Đã gửi yêu cầu tham gia nhóm, vui lòng chờ admin duyệt",
        "request_id": join_request.id,
        "status": "pending"
    }

@router.get("/{invite_code}")
def preview_invite(
    invite_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.invite_code == invite_code
    ).first()

    if not invite:
        raise HTTPException(404, "Link mời không tồn tại")

    if invite.is_active != 1:
        raise HTTPException(400, "Link mời đã bị tắt")

    conversation = db.query(Conversation).filter(
        Conversation.id == invite.conversation_id
    ).first()

    if not conversation or conversation.status == "deleted":
        raise HTTPException(404, "Nhóm không tồn tại")

    member_count = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation.id
    ).count()

    already_joined = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == conversation.id,
        ConversationMember.user_id == current_user.id
    ).first() is not None

    pending_request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.conversation_id == conversation.id,
        GroupJoinRequest.user_id == current_user.id,
        GroupJoinRequest.status == "pending"
    ).first() is not None

    return {
        "conversation_id": conversation.id,
        "name": conversation.name,
        "image": conversation.image,
        "member_count": member_count,
        "already_joined": already_joined,
        "require_approval": invite.require_approval,
        "pending_request": pending_request
    }

@router.patch("/conversations/{conversation_id}/require-approval")
def set_require_approval(
    conversation_id: int,
    require_approval: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    invite = db.query(GroupInviteLink).filter(
        GroupInviteLink.conversation_id == conversation_id
    ).first()

    if not invite:
        raise HTTPException(404, "Chưa có link mời")

    if require_approval not in [0, 1]:
        raise HTTPException(400, "require_approval chỉ được là 0 hoặc 1")

    invite.require_approval = require_approval
    db.commit()

    return {
        "message": "Đã cập nhật chế độ duyệt thành viên",
        "conversation_id": conversation_id,
        "require_approval": invite.require_approval
    }

@router.get("/conversations/{conversation_id}/requests")
def get_join_requests(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_conversation_or_404(db, conversation_id)
    check_admin_or_owner(db, conversation_id, current_user.id)

    requests = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.conversation_id == conversation_id,
        GroupJoinRequest.status == "pending"
    ).order_by(GroupJoinRequest.created_at.desc()).all()

    result = []

    for r in requests:
        user = db.query(User).filter(User.id == r.user_id).first()

        result.append({
            "id": r.id,
            "conversation_id": r.conversation_id,
            "user_id": r.user_id,
            "full_name": user.full_name if user else None,
            "avatar": user.avatar if user else None,
            "status": r.status,
            "created_at": r.created_at
        })

    return result

@router.patch("/requests/{request_id}/approve")
async def approve_join_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    join_request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.id == request_id
    ).first()

    if not join_request:
        raise HTTPException(404, "Yêu cầu tham gia không tồn tại")

    if join_request.status != "pending":
        raise HTTPException(400, "Yêu cầu này đã được xử lý")

    get_conversation_or_404(db, join_request.conversation_id)
    check_admin_or_owner(db, join_request.conversation_id, current_user.id)

    existing_member = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == join_request.conversation_id,
        ConversationMember.user_id == join_request.user_id
    ).first()

    if existing_member:
        join_request.status = "approved"
        join_request.handled_by = current_user.id
        join_request.handled_at = datetime.utcnow()
        db.commit()

        return {
            "message": "User đã ở trong nhóm từ trước"
        }

    db.add(ConversationMember(
        conversation_id=join_request.conversation_id,
        user_id=join_request.user_id,
        role="member"
    ))

    join_request.status = "approved"
    join_request.handled_by = current_user.id
    join_request.handled_at = datetime.utcnow()

    db.commit()

    members = db.query(ConversationMember).filter(
        ConversationMember.conversation_id == join_request.conversation_id
    ).all()

    member_ids = [m.user_id for m in members]

    await manager.send_to_many(member_ids, {
        "type": "group_join_request_approved",
        "conversation_id": join_request.conversation_id,
        "request_id": join_request.id,
        "user_id": join_request.user_id,
        "approved_by": current_user.id
    })

    return {
        "message": "Đã duyệt thành viên vào nhóm",
        "conversation_id": join_request.conversation_id,
        "user_id": join_request.user_id
    }

@router.patch("/requests/{request_id}/reject")
async def reject_join_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    join_request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.id == request_id
    ).first()

    if not join_request:
        raise HTTPException(404, "Yêu cầu tham gia không tồn tại")

    if join_request.status != "pending":
        raise HTTPException(400, "Yêu cầu này đã được xử lý")

    get_conversation_or_404(db, join_request.conversation_id)
    check_admin_or_owner(db, join_request.conversation_id, current_user.id)

    join_request.status = "rejected"
    join_request.handled_by = current_user.id
    join_request.handled_at = datetime.utcnow()

    db.commit()

    await manager.send_to_user(join_request.user_id, {
        "type": "group_join_request_rejected",
        "conversation_id": join_request.conversation_id,
        "request_id": join_request.id,
        "rejected_by": current_user.id
    })

    return {
        "message": "Đã từ chối yêu cầu tham gia nhóm",
        "request_id": join_request.id
    }

@router.get("/my-requests")
def get_my_join_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    requests = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.user_id == current_user.id
    ).order_by(GroupJoinRequest.created_at.desc()).all()

    result = []

    for r in requests:
        conversation = db.query(Conversation).filter(
            Conversation.id == r.conversation_id
        ).first()

        result.append({
            "id": r.id,
            "conversation_id": r.conversation_id,
            "group_name": conversation.name if conversation else None,
            "group_image": conversation.image if conversation else None,
            "status": r.status,
            "created_at": r.created_at,
            "handled_at": r.handled_at
        })

    return result