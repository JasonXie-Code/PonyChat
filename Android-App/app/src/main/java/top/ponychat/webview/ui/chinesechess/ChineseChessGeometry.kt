package top.ponychat.webview.ui.chinesechess

import androidx.compose.ui.geometry.Offset
import kotlin.math.min
import kotlin.math.roundToInt

internal data class BoardMetrics(
    val left: Float,
    val top: Float,
    val cell: Float,
    val pieceRadius: Float
) {
    fun x(col: Int): Float = left + col * cell
    fun y(row: Int): Float = top + row * cell
    fun center(cell: Cell): Offset = Offset(x(cell.x), y(cell.y))
}

internal fun boardMetrics(width: Float, height: Float): BoardMetrics {
    val horizontalMargin = width * 0.08f
    val verticalMargin = height * 0.065f
    val cell = min((width - horizontalMargin * 2f) / 8f, (height - verticalMargin * 2f) / 9f)
    val left = (width - cell * 8f) / 2f
    val top = (height - cell * 9f) / 2f
    return BoardMetrics(left, top, cell, cell * 0.418f)
}

internal fun boardCellAt(offset: Offset, width: Float, height: Float, perspective: Side): Cell? {
    val metrics = boardMetrics(width, height)
    val x = ((offset.x - metrics.left) / metrics.cell).roundToInt()
    val y = ((offset.y - metrics.top) / metrics.cell).roundToInt()
    if (x !in 0..8 || y !in 0..9) return null
    val displayCell = Cell(x, y)
    val center = metrics.center(displayCell)
    val dx = offset.x - center.x
    val dy = offset.y - center.y
    return if (dx * dx + dy * dy <= metrics.cell * metrics.cell * 0.34f) {
        displayCell.toLogicalCell(perspective)
    } else {
        null
    }
}

internal fun Cell.toDisplayCell(perspective: Side): Cell =
    if (perspective == Side.Red) this else Cell(8 - x, 9 - y)

internal fun Cell.toLogicalCell(perspective: Side): Cell =
    if (perspective == Side.Red) this else Cell(8 - x, 9 - y)