import asyncio,logging
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from core.review_translation import ReviewTranslations

class ReviewTranslationInput(BaseModel):
    user_id:str=Field(min_length=1,max_length=200)

def create_review_translation_router(store_getter,translator):
    router=APIRouter();locks={};logger=logging.getLogger(__name__)
    @router.get('/feedback/{id}/translation')
    def get_translation(id:str):
        try:return ReviewTranslations(store_getter()).get(id)
        except KeyError as error:raise HTTPException(404,str(error))
    @router.post('/feedback/{id}/translation')
    async def translate_review(id:str,body:ReviewTranslationInput):
        service=ReviewTranslations(store_getter())
        try:
            async with locks.setdefault(id,asyncio.Lock()):
                return await service.ensure(id,body.user_id,lambda review:translator(review,body.user_id))
        except KeyError as error:raise HTTPException(404,str(error))
        except ValueError as error:raise HTTPException(409,str(error))
        except HTTPException:raise
        except Exception as error:
            logger.warning('Historical review translation failed: %s',type(error).__name__)
            raise HTTPException(503,'中文译文暂未生成，原文仍可阅读，请稍后重试')
    return router
