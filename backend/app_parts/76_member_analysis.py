from .ai.member_history import analyze_member_history


@router.get('/api/members/{member_id}/recommendation-analysis')
def member_recommendation_analysis(member_id: int, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    with con() as c:
        try:
            return analyze_member_history(c, member_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))


@router.get('/api/member-analysis/summary')
def member_analysis_summary(limit: int = 50, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    limit = max(1, min(200, int(limit or 50)))
    with con() as c:
        members = c.execute('SELECT id,name FROM members ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        rows = []
        for member in members:
            try:
                profile = analyze_member_history(c, int(member['id']))
            except Exception:
                continue
            rows.append({
                'member_id': profile['member_id'],
                'member_name': profile['member_name'],
                'enabled': profile['enabled'],
                'evaluated_runs': profile['evaluated_runs'],
                'best_strategy': profile['best_strategy'],
                'confidence': profile['confidence'],
                'overall': profile['overall'],
            })
    return {'items': rows, 'count': len(rows)}
