"""Separate API fixture for a domain not used by the order/note examples.

This is a development holdout fixture, not an independent real-world benchmark.
"""
from fastapi import APIRouter, HTTPException

router=APIRouter(prefix='/inventory')


@router.get('/{variant}/')
def entry(variant: str):
    return {'schema':{'stock':'stock','property':'available','minimum':0},'version':'holdout-inventory-v1'}


@router.get('/{variant}/stock')
def stock(variant: str):
    if variant=='unavailable':raise HTTPException(503,'Controlled dependency outage')
    if variant not in {'healthy','negative'}:raise HTTPException(404)
    return {'sku':'sample-item','available':-3 if variant=='negative' else 7}
