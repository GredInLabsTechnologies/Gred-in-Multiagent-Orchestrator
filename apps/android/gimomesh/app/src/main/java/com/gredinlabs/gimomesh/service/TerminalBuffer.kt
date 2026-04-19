package com.gredinlabs.gimomesh.service

import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.model.TerminalLine
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Ring buffer for terminal log lines.
 * Thread-safe, zero-allocation when full (overwrites oldest).
 * In Blackout mode the buffer keeps collecting — only UI rendering stops.
 */
class TerminalBuffer(private val capacity: Int = 5000) {

    private val buffer = ArrayDeque<TerminalLine>(capacity)
    private val _lines = MutableStateFlow<List<TerminalLine>>(emptyList())
    val lines: StateFlow<List<TerminalLine>> = _lines.asStateFlow()

    @Synchronized
    fun append(source: LogSource, message: String, level: LogLevel = LogLevel.INFO) {
        val line = TerminalLine(
            timestamp = System.currentTimeMillis(),
            source = source,
            message = message,
            level = level,
        )
        if (buffer.size >= capacity) {
            buffer.removeFirst()
        }
        buffer.addLast(line)
        _lines.value = buffer.toList()
    }

    @Synchronized
    fun clear() {
        buffer.clear()
        _lines.value = emptyList()
    }

    @Synchronized
    fun snapshot(): List<TerminalLine> = buffer.toList()

    val size: Int get() = buffer.size
}
