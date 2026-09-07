"""Derived balances. Callers own commits, always lock account before G12 ledger."""
import os
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import text
from app.users.models import UserCreditAccount, UserCreditLedger, UserMandate


def welcome_amount():
    try:
        amount=Decimal(os.environ.get('WELCOME_CREDIT_USDC','0.05'))
        if not amount.is_finite() or amount<=0 or amount.as_tuple().exponent < -6: raise ValueError()
        return amount.quantize(Decimal('0.000001'))
    except (ValueError,InvalidOperation):raise RuntimeError('WELCOME_CREDIT_INVALID') from None


def balance(session,user_id):
    row=session.execute(text('SELECT total_credit,reserved_credit,spent_credit,available_credit FROM user_credit_balances WHERE user_id=:uid'),{'uid':user_id}).mappings().one()
    return {k:Decimal(v) for k,v in row.items()}


def lock_account(session,user_id):
    if session.get(UserCreditAccount,user_id,with_for_update=True) is None:raise RuntimeError('USER_ACCOUNT_MISSING')


def append(session,user_id,event_type,amount,key,mandate_id=None,acquisition_id=None):
    existing=session.query(UserCreditLedger).filter_by(idempotency_key=key).one_or_none()
    if existing:
        if (existing.user_id,existing.event_type,existing.amount,existing.mandate_id,existing.acquisition_id)!=(user_id,event_type,amount,mandate_id,acquisition_id):raise RuntimeError('USER_CREDIT_IDEMPOTENCY_CONFLICT')
        return existing
    row=UserCreditLedger(user_id=user_id,event_type=event_type,amount=amount,mandate_id=mandate_id,acquisition_id=acquisition_id,idempotency_key=key)
    session.add(row);session.flush()
    return row


def grant_welcome(session,user_id):
    lock_account(session,user_id)
    key=f'{user_id}:WELCOME_CREDIT'
    existing=session.query(UserCreditLedger).filter_by(idempotency_key=key).one_or_none()
    return existing or append(session,user_id,'WELCOME_CREDIT',welcome_amount(),key)


def reserve(session,user_id,mandate_id,amount):
    lock_account(session,user_id)
    if amount>balance(session,user_id)['available_credit']:raise HTTPException(422,'USER_CREDIT_INSUFFICIENT')
    return append(session,user_id,'SPEND_RESERVATION',amount,f'{mandate_id}:SPEND_RESERVATION',mandate_id)


def held(session,mandate_id):
    return Decimal(session.execute(text("SELECT coalesce(sum(CASE WHEN event_type='SPEND_RESERVATION' THEN amount WHEN event_type IN ('SPEND_SETTLEMENT','RESERVATION_RELEASE') THEN -amount ELSE 0 END),0) FROM user_credit_ledger WHERE mandate_id=:mid"),{'mid':mandate_id}).scalar_one())


def owner(session,mandate):
    if mandate.origin!='USER':return None
    link=session.get(UserMandate,mandate.mandate_id)
    if link is None or link.user_id!=mandate.actor_id:raise RuntimeError('USER_CREDIT_OWNER_INVALID')
    lock_account(session,link.user_id)
    return link.user_id


def verify_reserved(session,mandate,amount):
    uid=owner(session,mandate)
    if uid and held(session,mandate.mandate_id)<amount:raise RuntimeError('USER_CREDIT_RESERVATION_INVALID')


def settle(session,mandate,acquisition_id,amount,*,finalize):
    uid=owner(session,mandate)
    if uid is None:return
    append(session,uid,'SPEND_SETTLEMENT',amount,f'{mandate.mandate_id}:{acquisition_id}:SPEND_SETTLEMENT',mandate.mandate_id,acquisition_id)
    if finalize:release(session,mandate,acquisition_id)


def release(session,mandate,acquisition_id=None):
    uid=owner(session,mandate)
    if uid is None:return
    remainder=held(session,mandate.mandate_id)
    key=f'{mandate.mandate_id}:{acquisition_id or "terminal"}:RESERVATION_RELEASE'
    if remainder>0:append(session,uid,'RESERVATION_RELEASE',remainder,key,mandate.mandate_id,acquisition_id)
