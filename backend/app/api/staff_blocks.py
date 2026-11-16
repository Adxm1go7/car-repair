"""Staff block time and remove blocks."""

from datetime import timedelta
from typing import Annotated, Final, Self

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, AwareDatetime, BaseModel, model_validator

from app.api.holds import local_iso
from app.api.validation import reject
from app.repositories.availability import load_policy
from app.schedule.blocks import BlockClashes, UnknownBay, create_block, remove_block
from app.staff.deps import NowDep, SessionDep, StaffDep, check_origin, current_staff

router = APIRouter(prefix="/staff", dependencies=[Depends(check_origin), Depends(current_staff)])

MAX_BLOCK: Final = timedelta(days=31)


def clean_note(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Please say what the block is for")
    if len(value) > 200:
        raise ValueError("The note can be at most 200 characters")
    return value


class BlockIn(BaseModel):
    bay_id: int | None  # None: every bay
    start: AwareDatetime
    end: AwareDatetime
    note: Annotated[str, AfterValidator(clean_note)]

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.end <= self.start:
            raise ValueError("The end must be after the start")
        if self.end - self.start > MAX_BLOCK:
            raise ValueError("A block can be at most 31 days")
        return self


class BlockCreatedOut(BaseModel):
    id: int


@router.post("/blocks", status_code=201, response_model=BlockCreatedOut)
def add_block(body: BlockIn, staff: StaffDep, session: SessionDep, now: NowDep) -> object:
    """409 lists what's in the way, so staff can call those customers first."""
    try:
        block = create_block(session, staff, body.bay_id, body.start, body.end, body.note, now)
    except UnknownBay as error:
        raise reject("Unknown bay") from error
    except BlockClashes as clashes:
        session.rollback()
        zone = load_policy(session).zone
        return JSONResponse(
            status_code=409,
            content={
                "detail": "clashes",
                "bookings": [
                    {
                        "reference": booking.reference,
                        "start": local_iso(booking.start_at, zone),
                        "bay": bay.name,
                    }
                    for booking, bay in clashes.bookings
                ],
                "blocks": [{"id": block.id, "note": block.note} for block in clashes.blocks],
            },
        )
    session.commit()
    return BlockCreatedOut(id=block.id)


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(block_id: int, staff: StaffDep, session: SessionDep, now: NowDep) -> None:
    try:
        remove_block(session, staff, block_id, now)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="No such block") from error
    session.commit()
