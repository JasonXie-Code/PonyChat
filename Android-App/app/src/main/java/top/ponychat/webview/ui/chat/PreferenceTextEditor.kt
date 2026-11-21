package top.ponychat.webview.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.theme.Primary

/** Reveal the caret, rather than the entire potentially screen-tall editor. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun PreferenceTextEditor(text: String, enabled: Boolean, onChange: (String) -> Unit) {
    var value by remember { mutableStateOf(TextFieldValue(text)) }
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
    var focused by remember { mutableStateOf(false) }
    val requester = remember { BringIntoViewRequester() }
    val density = LocalDensity.current
    val imeBottom = WindowInsets.ime.getBottom(density)
    LaunchedEffect(text) {
        if (text != value.text) value = TextFieldValue(text)
    }
    LaunchedEffect(focused, imeBottom, value.selection, layout) {
        val result = layout
        if (focused && result != null && result.layoutInput.text.text == value.text) {
            // Insets update during the keyboard animation; wait for the resized viewport.
            withFrameNanos { }
            val caret = result.getCursorRect(value.selection.end.coerceIn(0, value.text.length))
            requester.bringIntoView(caret.inflate(with(density) { 8.dp.toPx() }))
        }
    }
    BasicTextField(
        value = value,
        onValueChange = {
            if (it.text.length <= 4000) {
                value = it
                onChange(it.text)
            }
        },
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().heightIn(min = 360.dp)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(18.dp))
            .padding(16.dp).bringIntoViewRequester(requester)
            .onFocusChanged { focused = it.isFocused },
        onTextLayout = { layout = it },
        textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onBackground),
        cursorBrush = SolidColor(Primary),
        decorationBox = { inner ->
            Box(Modifier.fillMaxWidth()) {
                if (text.isEmpty()) Text("例如：叫我小云；回复简短自然；少用反问句；我难过时先安慰我。",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f))
                inner()
            }
        },
    )
}
