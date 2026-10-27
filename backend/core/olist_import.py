"""Deterministic local-only Olist sample; zero model/embedding calls."""
import csv
from pathlib import Path
from core.workbench import WorkbenchStore, now

SOURCE_URL = 'https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce'


def import_sample(raw_dir, store=None, limit=120):
    if not 1 <= limit <= 200:
        raise ValueError('样本必须为1—200条')
    store = store or WorkbenchStore()
    raw = Path(raw_dir)
    with (raw/'olist_order_reviews_dataset.csv').open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    # Stable selection: low scores with body, sorted by review_id then order_id.
    eligible = sorted((r for r in rows if r['review_comment_message'].strip() and int(r['review_score']) <= 2), key=lambda r: (r['review_id'], r['order_id']))
    selected = eligible[:limit]
    ids = {r['order_id'] for r in selected}
    with (raw/'olist_orders_dataset.csv').open(newline='', encoding='utf-8') as f:
        orders = {r['order_id']: r for r in csv.DictReader(f) if r['order_id'] in ids}
    customers = {o['customer_id'] for o in orders.values()}
    with (raw/'olist_customers_dataset.csv').open(newline='', encoding='utf-8') as f:
        people = {r['customer_id']:r for r in csv.DictReader(f) if r['customer_id'] in customers}
    items = {id:[] for id in ids}
    with (raw/'olist_order_items_dataset.csv').open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['order_id'] in ids:
                items[row['order_id']].append(dict(product_id=row['product_id'], price=float(row['price']), freight=float(row['freight_value'])))
    for id, row in orders.items():
        customer = people.get(row['customer_id'], {})
        store.put('order', dict(id=id, customer_id=row['customer_id'], status=row['order_status'],
                  purchased_at=row['order_purchase_timestamp'], delivered_at=row['order_delivered_customer_date'],
                  estimated_at=row['order_estimated_delivery_date'], city=customer.get('customer_city', ''), state=customer.get('customer_state', ''),
                  currency='BRL', items=items[id], total=round(sum(i['price']+i['freight'] for i in items[id]),2),
                  source='Olist匿名真实历史订单（2016—2018）；只读样本，非实时订单'))
    for r in selected:
        store.put('review', dict(id=r['review_id']+':'+r['order_id'], review_id=r['review_id'], order_id=r['order_id'], score=int(r['review_score']), title=r['review_comment_title'], content=r['review_comment_message'], created_at=r['review_creation_date'], review_creation_date=r['review_creation_date'], review_answer_timestamp=r.get('review_answer_timestamp') or None, source='Olist真实历史评价，葡萄牙语原文；不代表客服政策'))
    manifest = dict(id='olist', source_url=SOURCE_URL, license='CC BY-NC-SA 4.0', historical_period='2016—2018', currency='BRL',
                    total_review_records=len(rows), eligible_records=len(eligible), imported_reviews=len(selected), imported_orders=len(orders),
                    filter=f'review_comment_message 非空；review_score <= 2；按 review_id、order_id 升序前{limit}条',
                    model_calls=0, embedding_calls=0, imported_at=now(), scope='匿名真实历史数据；本地演示；未连接实时客服或订单平台')
    store.put('dataset', manifest)
    return manifest


def backfill_review_times(raw_dir,store=None):
    """Enrich imported rows only; keep original text, legacy dates and case histories intact."""
    import json
    store=store or WorkbenchStore()
    with (Path(raw_dir)/'olist_order_reviews_dataset.csv').open(newline='',encoding='utf-8') as f:
        source={(r['review_id'],r['order_id']):r for r in csv.DictReader(f)}
    count=0
    with store.connect() as db:
        for id,raw in db.execute("SELECT id,data FROM records WHERE kind='review'").fetchall():
            record=json.loads(raw);original=source.get((record['review_id'],record['order_id']))
            if not original:continue
            updates=dict(review_creation_date=original['review_creation_date'],review_answer_timestamp=original.get('review_answer_timestamp') or None)
            if any(record.get(k)!=v for k,v in updates.items()):
                record.update(updates);db.execute("UPDATE records SET data=? WHERE kind='review' AND id=?",(json.dumps(record,ensure_ascii=False),id));count+=1
    return dict(updated=count,scope='仅补齐原始评价时间字段，未改写原文、订单或会话')
