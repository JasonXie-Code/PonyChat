package top.ponychat.companion.agent

/** Coordinates explicit user takeover with the Agent runtime. */
object CompanionExecutionControl {
    enum class Permission { CONTINUE, RESUMED, STOPPED }
    enum class Snapshot { IDLE, RUNNING, PAUSED, STOPPED }

    private enum class State { IDLE, RUNNING, PAUSED, STOPPED }

    private val lock = Object()
    private var state = State.IDLE

    fun beginTask() = synchronized(lock) {
        state = State.RUNNING
        lock.notifyAll()
    }

    fun pauseByUser(): Boolean = synchronized(lock) {
        if (state != State.RUNNING) return@synchronized false
        state = State.PAUSED
        true
    }

    fun continueTask() = synchronized(lock) {
        if (state == State.PAUSED) {
            state = State.RUNNING
            lock.notifyAll()
        }
    }

    fun stopTask() = synchronized(lock) {
        if (state == State.RUNNING || state == State.PAUSED) {
            state = State.STOPPED
            lock.notifyAll()
        }
    }

    fun awaitPermission(): Permission = synchronized(lock) {
        val wasPaused = state == State.PAUSED
        while (state == State.PAUSED) lock.wait()
        when {
            state == State.STOPPED -> Permission.STOPPED
            wasPaused -> Permission.RESUMED
            else -> Permission.CONTINUE
        }
    }

    fun finishTask() = synchronized(lock) {
        state = State.IDLE
        lock.notifyAll()
    }

    fun snapshot(): Snapshot = synchronized(lock) {
        Snapshot.valueOf(state.name)
    }
}
