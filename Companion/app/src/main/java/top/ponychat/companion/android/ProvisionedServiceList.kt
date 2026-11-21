package top.ponychat.companion.android

internal object ProvisionedServiceList {
    fun merge(current: String?, component: String): String =
        buildList {
            current.orEmpty()
                .split(':')
                .map(String::trim)
                .filter(String::isNotEmpty)
                .forEach { if (it !in this) add(it) }
            if (component !in this) add(component)
        }.joinToString(":")

    fun contains(current: String?, component: String): Boolean =
        current.orEmpty()
            .split(':')
            .map(String::trim)
            .any { it == component }
}
