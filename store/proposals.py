"""Kitchen-scoped, stable pages and counts for the approval inbox."""


def page(db, kitchen_id, *, cursor=None, limit=100):
    query = {'kitchen_id': kitchen_id}
    if cursor is not None:
        anchor = db.proposals.find_one({'_id': cursor, 'kitchen_id': kitchen_id}, {'created_at': 1})
        if anchor is None:
            raise ValueError('invalid proposal cursor')
        query['$or'] = [{'created_at': {'$lt': anchor['created_at']}},
                        {'created_at': anchor['created_at'], '_id': {'$lt': cursor}}]
    docs = list(db.proposals.find(query).sort([('created_at', -1), ('_id', -1)]).limit(limit + 1))
    more = len(docs) > limit
    docs = docs[:limit]
    return docs, docs[-1]['_id'] if more else None


def pending_count(db, kitchen_id):
    # READY is displayed as PENDING by the web; PENDING in storage is still building.
    return db.proposals.count_documents({'kitchen_id': kitchen_id, 'status': 'READY'})
