package top.ponychat.webview.ui.common

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.snapping.rememberSnapFlingBehavior
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import top.ponychat.webview.ui.theme.AppFontSizes
import top.ponychat.webview.ui.theme.Primary
import kotlin.math.roundToInt

/**
 * 滚轮日期选择器（与 Web wheel-date-picker 一致：年/月/日三列可滚动选择）
 */
@Composable
fun WheelDatePickerDialog(
    title: String = "选择日期",
    minYear: Int,
    maxYear: Int,
    selectedYear: Int,
    selectedMonth: Int,
    selectedDay: Int,
    onDateSelected: (year: Int, month: Int, day: Int) -> Unit,
    onDismiss: () -> Unit
) {
    var year by remember(selectedYear) { mutableStateOf(selectedYear) }
    var month by remember(selectedMonth) { mutableStateOf(selectedMonth) }
    var day by remember(selectedDay) { mutableStateOf(selectedDay) }

    val maxDayForMonth = remember(year, month) {
        when (month) {
            2 -> if (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) 29 else 28
            4, 6, 9, 11 -> 30
            else -> 31
        }
    }
    if (day > maxDayForMonth) day = maxDayForMonth

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(20.dp),
        title = {
            Text(title, color = MaterialTheme.colorScheme.onBackground)
        },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Row(modifier = Modifier.fillMaxWidth()) {
                    WheelLabel("年", Modifier.weight(1f))
                    WheelLabel("月", Modifier.weight(1f))
                    WheelLabel("日", Modifier.weight(1f))
                }
                Spacer(Modifier.height(8.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(wheelItemHeight * visibleItemsCount)
                        .clip(RoundedCornerShape(14.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(wheelItemHeight)
                            .align(Alignment.Center)
                            .background(
                                Brush.verticalGradient(
                                    colors = listOf(
                                        Primary.copy(alpha = 0.15f),
                                        Primary.copy(alpha = 0.08f)
                                    )
                                )
                            )
                    )
                    Row(modifier = Modifier.fillMaxSize()) {
                        WheelColumn(
                            label = "年",
                            values = (minYear..maxYear).toList(),
                            selectedValue = year,
                            onValueChange = { year = it },
                            suffix = "",
                            modifier = Modifier.weight(1f),
                            showLabel = false,
                            showContainer = false,
                            showSelectedBackground = false,
                            showMasks = false
                        )
                        WheelColumn(
                            label = "月",
                            values = (1..12).toList(),
                            selectedValue = month,
                            onValueChange = { month = it },
                            suffix = "月",
                            modifier = Modifier.weight(1f),
                            showLabel = false,
                            showContainer = false,
                            showSelectedBackground = false,
                            showMasks = false
                        )
                        WheelColumn(
                            label = "日",
                            values = (1..maxDayForMonth).toList(),
                            selectedValue = day,
                            onValueChange = { day = it },
                            suffix = "日",
                            modifier = Modifier.weight(1f),
                            showLabel = false,
                            showContainer = false,
                            showSelectedBackground = false,
                            showMasks = false
                        )
                    }
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(wheelItemHeight * (visibleItemsCount / 2))
                            .align(Alignment.TopCenter)
                            .background(
                                Brush.verticalGradient(
                                    colors = listOf(
                                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                                        Color.Transparent
                                    )
                                )
                            )
                    )
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(wheelItemHeight * (visibleItemsCount / 2))
                            .align(Alignment.BottomCenter)
                            .background(
                                Brush.verticalGradient(
                                    colors = listOf(
                                        Color.Transparent,
                                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                                    )
                                )
                            )
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onDateSelected(year, month, day) }) {
                Text("确定", color = Primary)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    )
}

private val wheelItemHeight: Dp = 40.dp
private const val visibleItemsCount = 5

@Composable
private fun WheelLabel(label: String, modifier: Modifier = Modifier) {
    Text(
        text = label,
        modifier = modifier,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = androidx.compose.ui.text.style.TextAlign.Center
    )
}

/**
 * 通用字符串滚轮选择列——可直接内嵌在任意布局中。
 *
 * 核心原理：contentPadding = visibleItems/2 * itemHeight 使 LazyColumn 滚到 item k 时
 * item k 恰好居中显示（padding 相当于上下各空出 visibleItems/2 行）。
 * 因此 centerIndex = firstVisibleItemIndex + round(scrollOffset / itemHeight)，
 * 不需要再加 columnHeight/2。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WheelStringColumn(
    items: List<String>,
    selectedItem: String,
    onItemSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
    visibleItems: Int = 3,
    accentColor: Color = Primary,
) {
    val selectedIndex = items.indexOf(selectedItem).coerceAtLeast(0)
    val listState = rememberLazyListState(
        initialFirstVisibleItemIndex = selectedIndex.coerceIn(0, (items.size - 1).coerceAtLeast(0))
    )
    val snapFlingBehavior = rememberSnapFlingBehavior(lazyListState = listState)
    val density = LocalDensity.current
    val itemHeightPx = with(density) { wheelItemHeight.roundToPx() }

    // 外部 selectedItem 改变时（如联动），把对应行滚到中心
    LaunchedEffect(selectedItem) {
        val idx = items.indexOf(selectedItem).coerceAtLeast(0)
        listState.animateScrollToItem(idx.coerceIn(0, (items.size - 1).coerceAtLeast(0)))
    }

    // 滚动结束后检测中心行并回调
    LaunchedEffect(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset) {
        val centerIndex = listState.firstVisibleItemIndex +
            (listState.firstVisibleItemScrollOffset.toFloat() / itemHeightPx).roundToInt()
        val clamped = centerIndex.coerceIn(0, items.size - 1)
        if (items[clamped] != selectedItem) {
            onItemSelected(items[clamped])
        }
    }

    val consumeAllScroll = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset =
                available
        }
    }
    val bgColor = MaterialTheme.colorScheme.surfaceVariant
    Box(
        modifier = modifier
            .height(wheelItemHeight * visibleItems)
            .clip(RoundedCornerShape(12.dp))
            .background(bgColor.copy(alpha = 0.45f))
            .nestedScroll(consumeAllScroll)
    ) {
        LazyColumn(
            state = listState,
            flingBehavior = snapFlingBehavior,
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(vertical = wheelItemHeight * (visibleItems / 2)),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            items(count = items.size, key = { it }) { index ->
                val value = items[index]
                val isSelected = value == selectedItem
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(wheelItemHeight)
                        .then(
                            if (isSelected) Modifier.background(
                                Brush.verticalGradient(
                                    listOf(accentColor.copy(alpha = 0.18f), accentColor.copy(alpha = 0.10f))
                                )
                            ) else Modifier
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = value,
                        style = MaterialTheme.typography.bodyLarge.copy(
                            fontSize = if (isSelected) AppFontSizes.headlineMedium else AppFontSizes.titleSmall
                        ),
                        color = if (isSelected) accentColor else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
        // 上下渐变遮罩
        Box(
            modifier = Modifier.fillMaxWidth()
                .height(wheelItemHeight * (visibleItems / 2))
                .align(Alignment.TopCenter)
                .background(Brush.verticalGradient(listOf(bgColor.copy(alpha = 0.65f), Color.Transparent)))
        )
        Box(
            modifier = Modifier.fillMaxWidth()
                .height(wheelItemHeight * (visibleItems / 2))
                .align(Alignment.BottomCenter)
                .background(Brush.verticalGradient(listOf(Color.Transparent, bgColor.copy(alpha = 0.65f))))
        )
        // 选中项指示线
        Box(
            modifier = Modifier.fillMaxWidth()
                .height(wheelItemHeight)
                .align(Alignment.Center)
                .background(Color.Transparent)
        ) {
            HorizontalDivider(color = accentColor.copy(alpha = 0.25f), modifier = Modifier.align(Alignment.TopCenter))
            HorizontalDivider(color = accentColor.copy(alpha = 0.25f), modifier = Modifier.align(Alignment.BottomCenter))
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun WheelColumn(
    label: String,
    values: List<Int>,
    selectedValue: Int,
    onValueChange: (Int) -> Unit,
    suffix: String,
    modifier: Modifier = Modifier,
    showLabel: Boolean = true,
    showContainer: Boolean = true,
    showSelectedBackground: Boolean = true,
    showMasks: Boolean = true,
) {
    val selectedIndex = values.indexOf(selectedValue).coerceIn(0, values.size - 1)
    val listState = rememberLazyListState(
        initialFirstVisibleItemIndex = selectedIndex
    )
    val snapFlingBehavior = rememberSnapFlingBehavior(lazyListState = listState)
    val density = LocalDensity.current
    val itemHeightPx = with(density) { wheelItemHeight.roundToPx() }

    LaunchedEffect(Unit) {
        listState.scrollToItem(selectedIndex)
    }

    LaunchedEffect(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset) {
        val centerIndex = listState.firstVisibleItemIndex +
            (listState.firstVisibleItemScrollOffset.toFloat() / itemHeightPx).roundToInt()
        val clamped = centerIndex.coerceIn(0, values.size - 1)
        if (clamped in values.indices && values[clamped] != selectedValue) {
            onValueChange(values[clamped])
        }
    }

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        if (showLabel) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(8.dp))
        }
        val consumeAllScroll = remember {
            object : NestedScrollConnection {
                override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset =
                    available
            }
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(wheelItemHeight * visibleItemsCount)
                .then(
                    if (showContainer) {
                        Modifier
                            .clip(RoundedCornerShape(12.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                    } else {
                        Modifier
                    }
                )
                .nestedScroll(consumeAllScroll)
        ) {
            LazyColumn(
                state = listState,
                flingBehavior = snapFlingBehavior,
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(vertical = wheelItemHeight * (visibleItemsCount / 2)),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(0.dp)
            ) {
                items(
                    count = values.size,
                    key = { values[it] }
                ) { index ->
                    val value = values[index]
                    val isSelected = value == selectedValue
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(wheelItemHeight)
                            .then(
                                if (isSelected && showSelectedBackground) Modifier.background(
                                    Brush.verticalGradient(
                                        colors = listOf(
                                            Primary.copy(alpha = 0.15f),
                                            Primary.copy(alpha = 0.08f)
                                        )
                                    )
                                ) else Modifier
                            ),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "$value$suffix",
                            style = MaterialTheme.typography.bodyLarge.copy(
                                fontSize = if (isSelected) AppFontSizes.headlineMedium else AppFontSizes.titleSmall
                            ),
                            color = if (isSelected) Primary else MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
            // 上下渐变遮罩，突出中间选中项
            if (showMasks) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(wheelItemHeight * (visibleItemsCount / 2))
                        .align(Alignment.TopCenter)
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                                    Color.Transparent
                                )
                            )
                        )
                )
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(wheelItemHeight * (visibleItemsCount / 2))
                        .align(Alignment.BottomCenter)
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    Color.Transparent,
                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                                )
                            )
                        )
                )
            }
        }
    }
}
