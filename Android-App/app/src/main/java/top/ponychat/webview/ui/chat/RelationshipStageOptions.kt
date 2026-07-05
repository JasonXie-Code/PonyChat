package top.ponychat.webview.ui.chat

internal val RELATIONSHIP_STAGE_KEYS = listOf(
    "new_contact",
    "uncertain",
    "familiar",
    "mentor_student",
    "trusted_companion",
    "family_like",
    "flirting",
    "committed_partner",
    "intimate_partner",
    "broken_up",
    "in_conflict",
    "mutual_dislike",
    "hurtful_dynamic"
)

internal fun normalizeRelationshipStageKey(value: String?): String {
    val key = value?.trim().orEmpty()
    return if (key in RELATIONSHIP_STAGE_KEYS) key else "uncertain"
}

internal fun relationshipStageCn(key: String): String = when (normalizeRelationshipStageKey(key)) {
    "new_contact" -> "新朋友"
    "uncertain" -> "未知"
    "familiar" -> "好朋友"
    "mentor_student" -> "师生"
    "trusted_companion" -> "可信同伴"
    "family_like" -> "家人般"
    "flirting" -> "暧昧对象"
    "committed_partner" -> "伴侣"
    "intimate_partner" -> "亲密伴侣"
    "broken_up" -> "已分手"
    "in_conflict" -> "吵架中"
    "mutual_dislike" -> "互相看不爽"
    "hurtful_dynamic" -> "互相伤害"
    else -> "未知"
}

internal fun isRomanticRelationshipStage(key: String): Boolean =
    normalizeRelationshipStageKey(key) in setOf(
        "flirting",
        "committed_partner",
        "intimate_partner"
    )

internal fun isNegativeRelationshipStage(key: String): Boolean =
    normalizeRelationshipStageKey(key) in setOf(
        "broken_up",
        "in_conflict",
        "mutual_dislike",
        "hurtful_dynamic"
    )

internal fun isNonRomanticPositiveRelationshipStage(key: String): Boolean =
    normalizeRelationshipStageKey(key) in setOf(
        "mentor_student",
        "trusted_companion",
        "family_like"
    )
