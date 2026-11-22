package top.ponychat.webview.ui.music

import android.text.format.DateUtils
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.automirrored.filled.ViewList
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.GridView
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.focus.FocusManager
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.common.AppFeedbackHost
import top.ponychat.webview.ui.common.PonyAlertDialog
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyButtonStyle
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyIconButton
import top.ponychat.webview.ui.common.PonyTopBarBackButton
import top.ponychat.webview.ui.common.PonyTopSearchBar
import top.ponychat.webview.ui.common.adaptivePopupMenuBorder
import top.ponychat.webview.ui.common.adaptivePopupMenuContainerColor
import top.ponychat.webview.ui.common.adaptivePopupMenuContentColor
import top.ponychat.webview.ui.common.adaptivePopupMenuDangerColor

private const val CATALOG = "曲库"
private const val MINE = "我的音乐"
private const val ALBUMS = "全部专辑"
private const val RECENT = "最近播放"
private const val FAVORITES = "我喜欢的"
private const val FAVORITE_ALBUMS = "收藏的专辑"
private const val FAVORITE_SONG_PREVIEW_COUNT = 3

@Composable
internal fun MusicScreen(
    model: MusicPlayerViewModel,
    openPlayer: () -> Unit,
    prefs: AppPreferences,
    requestedAlbum: String?,
    onAlbumRequestHandled: () -> Unit,
    bottomBar: @Composable () -> Unit,
) {
    val state by model.catalog.collectAsStateWithLifecycle()
    val account by MusicAccountStore.state.collectAsStateWithLifecycle()
    val library = account.library
    val syncError by model.syncError.collectAsStateWithLifecycle()
    val libraryError = syncError?.takeUnless { it.mutation }
    val messages = CustomToast.current
    val playbackMessages = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    LaunchedEffect(syncError) {
        syncError?.takeIf { it.mutation }?.let { messages.showSnackbar(it.message) }
    }
    val trackIndicator = remember(model) {
        model.playerState.map { it.item?.id to it.playing }.distinctUntilChanged()
    }
    val activeTrack by trackIndicator.collectAsStateWithLifecycle(initialValue = null to false)
    val syncing by model.syncing.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableStateOf(CATALOG) }
    var page by rememberSaveable { mutableStateOf<String?>(null) }
    var albumParent by rememberSaveable { mutableStateOf<String?>(null) }
    var category by rememberSaveable { mutableStateOf(MusicAlbumCategory.ALL) }
    var albumGrid by remember { mutableStateOf(prefs.musicAlbumGrid) }
    var query by rememberSaveable { mutableStateOf("") }
    var versions by rememberSaveable { mutableStateOf(false) }
    var sortOrder by rememberSaveable { mutableStateOf(MusicSortOrder.DEFAULT) }
    var displayedSortOrder by remember { mutableStateOf(sortOrder) }
    var addSong by rememberSaveable { mutableStateOf<String?>(null) }
    var namePlaylist by rememberSaveable { mutableStateOf<String?>(null) }
    var confirm by rememberSaveable { mutableStateOf<String?>(null) }
    val search = rememberMusicSearch(query)
    val catalog = state.data
    val album = catalog?.albumsById?.get(page)
    val colors = MaterialTheme.colorScheme
    val albumArtwork = album?.let { MusicSite.mediaUri(it.cover)?.toString() }
    val favoriteCover = library?.favorites?.firstOrNull()
        ?.let { catalog?.songsById?.get(it) }
        ?.let { catalog?.albumsById?.get(it.albumId)?.cover }
    val favoritesPage = page == FAVORITES
    val favoriteArtwork = MusicSite.mediaUri(favoriteCover)?.toString()
    val collectionArtwork = if (favoritesPage) favoriteArtwork else albumArtwork
    val showCollectionBackground = album != null || (favoritesPage && collectionArtwork != null)
    val background = if (!showCollectionBackground) Modifier else {
        val tint = MusicArtworkTint(collectionArtwork, colors.surfaceVariant)
        Modifier.background(
            Brush.verticalGradient(
                0f to tint,
                0.34f to lerp(tint, colors.background, 0.26f),
                0.80f to colors.background,
                1f to colors.background,
            )
        )
    }
    val playlist = library?.playlists?.firstOrNull { it.id == page }
    val favoriteSongIds = sortOrder.sort(
        library?.favorites.orEmpty(),
        title = { catalog?.songsById?.get(it)?.title ?: it },
        releaseDate = { catalog?.songsById?.get(it)?.releaseDate },
    )
    val favoriteAlbumIds = sortOrder.sort(
        library?.favoriteAlbums.orEmpty(),
        title = { catalog?.albumsById?.get(it)?.title ?: it },
        releaseDate = { catalog?.albumsById?.get(it)?.releaseDate },
    )
    val focus = LocalFocusManager.current
    val allAlbumsListState = rememberLazyListState()
    val allAlbumsGridState = rememberLazyListState()
    val savedAlbumsListState = rememberLazyListState()
    val savedAlbumsGridState = rememberLazyListState()
    val categoryState = rememberLazyListState()
    val albumRailState = rememberLazyListState()
    val savedAlbumRailState = rememberLazyListState()
    val visibleAlbums = remember(catalog, category, sortOrder) {
        sortOrder.sortCatalogAlbums(catalog?.albums.orEmpty().filter(category::matches))
    }
    val categories = remember(catalog) {
        MusicAlbumCategory.entries.filter { group ->
            group == MusicAlbumCategory.ALL || catalog?.albums?.any(group::matches) == true
        }
    }
    val albumCollection = page == ALBUMS || page == FAVORITE_ALBUMS

    fun selectCategory(next: MusicAlbumCategory) {
        if (category == next) return
        category = next
        albumRailState.requestScrollToItem(0)
        allAlbumsListState.requestScrollToItem(0)
        allAlbumsGridState.requestScrollToItem(0)
    }

    fun openAlbum(id: String) {
        if (page == id) return
        if (album == null) albumParent = page
        focus.clearFocus()
        page = id
    }

    LaunchedEffect(requestedAlbum) {
        if (requestedAlbum != null) {
            openAlbum(requestedAlbum)
            onAlbumRequestHandled()
        }
    }

    LaunchedEffect(Unit) { model.loadCatalog() }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, model) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) model.refreshLibrary()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    fun goBack() {
        page = albumParent
        albumParent = null
    }

    fun queueNext(song: MusicSong) {
        model.playNext(song, catalog?.albumsById?.get(song.albumId)) { message ->
            scope.launch {
                if (playbackMessages.currentSnackbarData?.visuals?.message != message) {
                    playbackMessages.showSnackbar(message)
                }
            }
        }
    }

    BackHandler(page != null) { goBack() }
    Scaffold(
        modifier = background,
        containerColor = if (showCollectionBackground) Color.Transparent else colors.background,
        contentColor = colors.onBackground,
        topBar = {
            Column(Modifier.statusBarsPadding().padding(horizontal = 18.dp)) {
                if (page == null) {
                    Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("音乐", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        MusicOptionsMenu(sortOrder, { sortOrder = it })
                    }
                    MusicTabs(listOf(CATALOG, MINE), tab) { next ->
                        focus.clearFocus()
                        tab = next
                        if (next == MINE) model.refreshLibrary()
                    }
                    if (tab == CATALOG) {
                        PonyTopSearchBar(
                            value = query,
                            onValueChange = { query = it.take(160) },
                            placeholder = "搜索歌曲、角色或歌词",
                            modifier = Modifier.fillMaxWidth().padding(top = 5.dp, bottom = 12.dp),
                        )
                    }
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        PonyTopBarBackButton(
                            onClick = ::goBack,
                            contentDescription = albumParent?.let { "返回$it" } ?: "返回音乐首页",
                        )
                        Text(
                            album?.let { "专辑" } ?: playlist?.name
                                ?: page.orEmpty().takeIf { it in setOf(ALBUMS, RECENT, FAVORITE_ALBUMS) }.orEmpty(),
                            style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        if (album != null || page in setOf(ALBUMS, FAVORITES, FAVORITE_ALBUMS)) {
                            MusicOptionsMenu(
                                sortOrder, { sortOrder = it },
                                albumVersions = versions.takeIf { album != null },
                                onVersionsChange = { versions = it },
                                showAlbumGrid = albumGrid.takeIf { albumCollection },
                                onAlbumLayoutChange = { grid ->
                                    albumGrid = grid
                                    prefs.musicAlbumGrid = grid
                                },
                            )
                        }
                        if (playlist != null) {
                            Box {
                                var more by rememberSaveable(playlist.id) { mutableStateOf(false) }
                                PonyIconButton(onClick = { more = true }, icon = Icons.Default.MoreVert, contentDescription = "管理歌单")
                                MusicTopDropdownMenu(more, { more = false }) {
                                    DropdownMenuItem(
                                        text = { Text("重命名") },
                                        leadingIcon = { Icon(Icons.Default.Edit, null) },
                                        colors = musicTopMenuItemColors(),
                                        onClick = { more = false; namePlaylist = playlist.id },
                                    )
                                    DropdownMenuItem(
                                        text = { Text("删除歌单") },
                                        leadingIcon = { Icon(Icons.Default.DeleteOutline, null) },
                                        colors = musicTopMenuItemColors(adaptivePopupMenuDangerColor()),
                                        onClick = { more = false; confirm = playlist.id },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        },
        bottomBar = {
            Surface {
                Column {
                    MusicMiniPlayer(model, openPlayer)
                    bottomBar()
                }
            }
        },
    ) { padding ->
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val gridColumns = ((maxWidth - 36.dp) / 148.dp).toInt().coerceIn(2, 5)
            val catalogPageState = rememberLazyListState()
            val minePageState = rememberLazyListState()
            val searchPageState = rememberLazyListState()
            LaunchedEffect(query) { if (query.isNotBlank()) searchPageState.scrollToItem(0) }
            key(page) {
                val listState = when (page) {
                    ALBUMS -> if (albumGrid) allAlbumsGridState else allAlbumsListState
                    FAVORITE_ALBUMS -> if (albumGrid) savedAlbumsGridState else savedAlbumsListState
                    null -> when {
                        tab == MINE -> minePageState
                        query.isNotBlank() -> searchPageState
                        else -> catalogPageState
                    }
                    else -> rememberLazyListState()
                }
                LaunchedEffect(sortOrder) {
                    if (displayedSortOrder != sortOrder) {
                        listState.requestScrollToItem(0)
                        displayedSortOrder = sortOrder
                    }
                }
                LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    state = listState,
                    contentPadding = PaddingValues(start = 18.dp, end = 18.dp, bottom = 22.dp),
                    verticalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    when {
                        page == null && tab == CATALOG -> {
                            if (catalog == null) catalogFeedback(state, model)
                            else if (query.isBlank()) {
                                item { AlbumCategories(categories, category, categoryState, ::selectCategory) }
                                item {
                                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                        Text("专辑", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                                        TextButton(onClick = { focus.clearFocus(); page = ALBUMS }) { Text("查看全部") }
                                    }
                                }
                                albumRail(visibleAlbums.take(12), albumRailState, ::openAlbum)
                                item {
                                    Text("我的", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(top = 12.dp))
                                }
                                if (library == null) {
                                    item {
                                        if (syncing) MusicMessage("正在同步收藏…")
                                        else MusicMessage("收藏暂时无法加载", "刷新", model::refreshLibrary)
                                    }
                                } else if (library.favorites.isEmpty() && library.favoriteAlbums.isEmpty()) {
                                    item { MusicMessage("收藏歌曲或专辑后，会显示在这里") }
                                } else {
                                    item {
                                        MusicSectionHeading("收藏的歌曲", onViewAll = if (library.favorites.isNotEmpty()) ({ page = FAVORITES }) else null)
                                    }
                                    if (library.favorites.isEmpty()) item { MusicEmptyCollection("还没有收藏的歌曲") }
                                    else musicSongs(
                                        favoriteSongIds, catalog, library, model, focus,
                                        add = { addSong = it },
                                        remove = { model.updateLibrary(MusicCommand("favorite", songId = it, enabled = false)) },
                                        previewCount = FAVORITE_SONG_PREVIEW_COUNT,
                                    )
                                    item {
                                        MusicSectionHeading(FAVORITE_ALBUMS, onViewAll = if (library.favoriteAlbums.isNotEmpty()) ({ page = FAVORITE_ALBUMS }) else null)
                                    }
                                    val savedAlbums = favoriteAlbumIds.mapNotNull(catalog.albumsById::get)
                                    if (library.favoriteAlbums.isEmpty()) item { MusicEmptyCollection("还没有收藏的专辑") }
                                    else if (savedAlbums.isEmpty()) item { MusicEmptyCollection("收藏的专辑暂不可用") }
                                    else albumRail(savedAlbums, savedAlbumRailState, ::openAlbum)
                                }
                            } else {
                                musicSearchResults(catalog, library, model, focus, search, sortOrder, add = { addSong = it })
                            }
                        }
                        page == null -> {
                            when {
                                syncing && library == null -> item { MusicMessage("正在同步…") }
                                library == null && libraryError == null -> item { MusicMessage("账号同步未就绪", "刷新", model::refreshLibrary) }
                                library != null -> {
                                    if (catalog != null && library.historyEnabled) {
                                        item { MusicResumeCard(model, catalog, library, versions, sortOrder) }
                                    }
                                    item {
                                        MusicCollectionRow(
                                            FAVORITES, "${library.favorites.size} 首", favoriteCover,
                                            blankCoverIfMissing = true,
                                        ) { page = FAVORITES }
                                    }
                                    item {
                                        val cover = library.favoriteAlbums.firstNotNullOfOrNull { catalog?.albumsById?.get(it)?.cover }
                                        MusicCollectionRow(FAVORITE_ALBUMS, "${library.favoriteAlbums.size} 张", cover) { page = FAVORITE_ALBUMS }
                                    }
                                    item {
                                        MusicCollectionRow(
                                            RECENT, "${library.history.size} 首",
                                            catalog?.collectionCover(library.history.map { it.songId }),
                                        ) { page = RECENT }
                                    }
                                    item {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text("自建歌单", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                                            TextButton(onClick = { namePlaylist = "" }) {
                                                Icon(Icons.Default.Add, null)
                                                Text("新建")
                                            }
                                        }
                                    }
                                    if (library.playlists.isEmpty()) item { MusicMessage("还没有歌单") }
                                    items(library.playlists, key = MusicPlaylist::id) { entry ->
                                        MusicCollectionRow(entry.name, "${entry.songIds.size} 首", catalog?.collectionCover(entry.songIds)) {
                                            page = entry.id
                                        }
                                    }
                                }
                            }
                        }
                        page == ALBUMS -> {
                            if (catalog == null) catalogFeedback(state, model)
                            else {
                                item { AlbumCategories(categories, category, categoryState, ::selectCategory) }
                                if (albumGrid) albumsInGrid(visibleAlbums, gridColumns, ::openAlbum)
                                else items(visibleAlbums, key = MusicAlbum::id) { entry ->
                                    MusicCollectionRow(entry.title, "${entry.trackCount} 首", entry.cover) { openAlbum(entry.id) }
                                }
                            }
                        }
                        page == FAVORITE_ALBUMS -> {
                            val ids = favoriteAlbumIds
                            if (ids.isEmpty()) item { MusicMessage("还没有收藏的专辑") }
                            else if (catalog == null) catalogFeedback(state, model)
                            else if (albumGrid) {
                                val albums = ids.map { catalog.albumsById[it] ?: MusicAlbum(it, it, null, 0) }
                                val unavailable = ids.filterNot(catalog.albumsById::containsKey).toSet()
                                albumsInGrid(albums, gridColumns, ::openAlbum, unavailable) { entry ->
                                    PonyIconButton(
                                        onClick = { model.updateLibrary(MusicCommand("favoriteAlbum", albumId = entry.id, enabled = false)) },
                                        icon = Icons.Default.Favorite,
                                        contentDescription = "取消收藏 ${entry.title}",
                                        tint = MaterialTheme.colorScheme.primary,
                                        size = 38.dp,
                                    )
                                }
                            }
                            else items(ids, key = { "savedAlbum:$it" }) { id ->
                                val savedAlbum = catalog.albumsById[id]
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Box(Modifier.weight(1f)) {
                                        MusicCollectionRow(
                                            title = savedAlbum?.title ?: id,
                                            subtitle = savedAlbum?.let { "${it.trackCount} 首" } ?: "专辑暂不可用",
                                            cover = savedAlbum?.cover,
                                            open = savedAlbum?.let { { openAlbum(id) } },
                                        )
                                    }
                                    PonyIconButton(
                                        onClick = { model.updateLibrary(MusicCommand("favoriteAlbum", albumId = id, enabled = false)) },
                                        icon = Icons.Default.Favorite,
                                        contentDescription = "取消收藏 ${savedAlbum?.title ?: id}",
                                        tint = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }
                        }
                        album != null -> {
                            val tracks = catalog.albumTracks(album.id, versions, sortOrder)
                            val saved = album.id in library?.favoriteAlbums.orEmpty()
                            item { AlbumHeader(album, albumArtwork, tracks) }
                            item {
                                AlbumActions(
                                    trackCount = tracks.size,
                                    saved = saved,
                                    canSave = library != null,
                                    onPlay = { model.play(tracks, catalog.albumsById, tracks.first().id) },
                                    onShuffle = { model.play(tracks, catalog.albumsById, tracks.random().id, shuffled = true) },
                                    onToggleSaved = {
                                        model.updateLibrary(MusicCommand("favoriteAlbum", albumId = album.id, enabled = !saved))
                                    },
                                )
                            }
                            musicSongs(
                                tracks.map { it.id }, catalog, library, model, focus,
                                add = { addSong = it },
                                showTrackNumbers = true,
                                activeTrack = activeTrack,
                                onPlayNext = ::queueNext,
                            )
                        }
                        page == RECENT -> {
                            if (library != null) {
                                item {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text("记录收听历史", Modifier.weight(1f))
                                        Switch(library.historyEnabled, { model.updateLibrary(MusicCommand("historySetting", enabled = it)) })
                                    }
                                    if (library.history.isNotEmpty()) {
                                        TextButton(onClick = { confirm = RECENT }) { Text("清空历史") }
                                    }
                                }
                                if (library.history.isEmpty()) item { MusicMessage("还没有播放记录") }
                            }
                            if (catalog == null) catalogFeedback(state, model)
                            else if (library != null) {
                                musicSongs(
                                    library.history.map { it.songId }, catalog, library, model, focus,
                                    history = library.history.associateBy { it.songId }, add = { addSong = it },
                                    remove = { model.updateLibrary(MusicCommand("removeHistory", songId = it)) },
                                )
                            }
                        }
                        favoritesPage -> {
                            item {
                                MusicCollectionHeader(
                                    title = FAVORITES,
                                    artwork = favoriteArtwork,
                                    metadata = library?.let { "${it.favorites.size} 首" }.orEmpty(),
                                    compactCover = true,
                                    blankCoverIfMissing = true,
                                )
                            }
                            when {
                                library == null -> item { MusicMessage("正在同步收藏…") }
                                favoriteSongIds.isEmpty() -> item { MusicMessage("还没有收藏的歌曲") }
                                catalog == null -> catalogFeedback(state, model)
                                else -> {
                                    item { PlayMusicCollection(favoriteSongIds.mapNotNull(catalog.songsById::get), catalog, model) }
                                    musicSongs(
                                        favoriteSongIds, catalog, library, model, focus,
                                        add = { addSong = it },
                                        remove = { model.updateLibrary(MusicCommand("favorite", songId = it, enabled = false)) },
                                        showTrackNumbers = true,
                                        activeTrack = activeTrack,
                                        onPlayNext = ::queueNext,
                                    )
                                }
                            }
                        }
                        playlist != null -> {
                            val ids = playlist.songIds
                            if (ids.isEmpty()) item { MusicMessage("歌单里还没有歌曲") }
                            if (catalog == null) catalogFeedback(state, model)
                            else {
                                item { PlayMusicCollection(ids.mapNotNull { catalog.songsById[it] }, catalog, model) }
                                musicSongs(
                                    ids, catalog, library, model, focus, add = { addSong = it },
                                    remove = { id -> model.updateLibrary(MusicCommand("removeSong", songId = id, playlistId = playlist.id)) },
                                    move = { id, direction ->
                                        model.updateLibrary(MusicCommand("moveSong", songId = id, playlistId = playlist.id, direction = direction))
                                    },
                                )
                            }
                        }
                        catalog == null -> catalogFeedback(state, model)
                        else -> item { MusicMessage("内容暂不可用", "返回", ::goBack) }
                    }
                }
            }
            AppFeedbackHost(
                playbackMessages,
                Modifier.align(Alignment.BottomCenter).padding(padding).padding(bottom = 8.dp),
            )
        }
    }

    if (tab == MINE && libraryError != null) {
        PonyConfirmDialog(
            title = "账号同步",
            message = libraryError.message,
            confirmText = "重试",
            onConfirm = {
                model.dismissSyncError(libraryError)
                model.refreshLibrary()
            },
            onDismiss = { model.dismissSyncError(libraryError) },
            dismissText = "关闭",
        )
    }

    addSong?.let { id -> AddSongDialog(id, library, model) { addSong = null } }
    namePlaylist?.let { id ->
        val existing = library?.playlists?.firstOrNull { it.id == id }
        PlaylistNameDialog(existing?.name, onDismiss = { namePlaylist = null }) { name ->
            if (existing == null) model.createPlaylist(name)
            else model.updateLibrary(MusicCommand("renamePlaylist", playlistId = id, name = name))
            namePlaylist = null
        }
    }
    confirm?.let { target ->
        val isHistory = target == RECENT
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (isHistory) "清空收听历史？" else "删除这个歌单？") },
            confirmButton = {
                TextButton(onClick = {
                    if (isHistory) model.updateLibrary(MusicCommand("clearHistory"))
                    else {
                        model.updateLibrary(MusicCommand("deletePlaylist", playlistId = target))
                        page = null
                    }
                    confirm = null
                }) { Text(if (isHistory) "清空" else "删除") }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("取消") } },
        )
    }
}

@Composable
internal fun MusicSearchScreen(model: MusicPlayerViewModel, close: () -> Unit) {
    val state by model.catalog.collectAsStateWithLifecycle()
    val account by MusicAccountStore.state.collectAsStateWithLifecycle()
    val syncError by model.syncError.collectAsStateWithLifecycle()
    val messages = CustomToast.current
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val searchField = remember { FocusRequester() }
    var query by rememberSaveable { mutableStateOf("") }
    var sortOrder by rememberSaveable { mutableStateOf(MusicSortOrder.DEFAULT) }
    var addSong by rememberSaveable { mutableStateOf<String?>(null) }
    val search = rememberMusicSearch(query)
    val list = rememberLazyListState()
    val catalog = state.data
    val library = account.library
    val returnToPlayer: () -> Unit = {
        focus.clearFocus()
        keyboard?.hide()
        close()
    }

    LaunchedEffect(Unit) {
        model.loadCatalog()
        model.refreshLibrary()
        withFrameNanos { }
        searchField.requestFocus()
        keyboard?.show()
    }
    LaunchedEffect(query, sortOrder) { list.scrollToItem(0) }
    LaunchedEffect(syncError) {
        syncError?.takeIf { it.mutation }?.let { messages.showSnackbar(it.message) }
    }

    Scaffold(
        topBar = {
            Row(
                Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PonyTopBarBackButton(onClick = returnToPlayer, contentDescription = "返回播放器")
                PonyTopSearchBar(
                    value = query,
                    onValueChange = { query = it.take(160) },
                    placeholder = "搜索歌曲、角色或歌词",
                    modifier = Modifier.weight(1f),
                    focusRequester = searchField,
                )
                MusicOptionsMenu(sortOrder, { sortOrder = it })
            }
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            state = list,
            contentPadding = PaddingValues(horizontal = 18.dp, vertical = 7.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            if (query.isNotBlank()) {
                if (catalog == null) catalogFeedback(state, model)
                else musicSearchResults(
                    catalog, library, model, focus, search, sortOrder,
                    add = {
                        focus.clearFocus()
                        keyboard?.hide()
                        addSong = it
                    },
                    onPlayed = returnToPlayer,
                )
            }
        }
    }
    addSong?.let { AddSongDialog(it, library, model) { addSong = null } }
}

private data class MusicSearchState(
    val results: List<MusicSearchHit>?,
    val failed: Boolean,
    val retry: () -> Unit,
)

@Composable
private fun rememberMusicSearch(query: String): MusicSearchState {
    var results by remember(query) { mutableStateOf<List<MusicSearchHit>?>(null) }
    var failed by remember(query) { mutableStateOf(false) }
    var retry by remember { mutableStateOf(0) }
    LaunchedEffect(query, retry) {
        results = null
        failed = false
        val term = query.trim()
        if (term.isEmpty()) return@LaunchedEffect
        delay(300)
        try {
            results = MusicSite.api.search(term, versions = false).songs
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            failed = true
        }
    }
    return MusicSearchState(results, failed) { retry++ }
}

private fun LazyListScope.musicSearchResults(
    catalog: MusicCatalog,
    library: MyMusic?,
    model: MusicPlayerViewModel,
    focus: FocusManager,
    search: MusicSearchState,
    sortOrder: MusicSortOrder,
    add: (String) -> Unit,
    onPlayed: (() -> Unit)? = null,
) {
    when {
        search.failed -> item { MusicMessage("搜索失败，请重试", "重试", search.retry) }
        search.results == null -> item { MusicMessage("正在搜索…") }
        search.results.isEmpty() -> item { MusicMessage("没有找到相关歌曲") }
        else -> {
            val matches = sortOrder.sort(
                search.results,
                title = { catalog.songsById[it.id]?.title ?: it.id },
                releaseDate = { catalog.songsById[it.id]?.releaseDate },
            )
            musicSongs(
                matches.map { it.id }, catalog, library, model, focus,
                matchedLyrics = matches.mapNotNull { hit -> hit.lyricSnippet?.let { hit.id to it } }.toMap(),
                add = add, onPlayed = onPlayed,
            )
        }
    }
}

private fun MusicCatalog.albumTracks(
    albumId: String,
    versions: Boolean,
    sortOrder: MusicSortOrder,
    include: MusicSong? = null,
): List<MusicSong> {
    val playable = songs.filter { it.albumId == albumId && it.src != null && it.supersededBy.isNullOrBlank() }
    val visible = if (versions) playable else playable.filter(MusicSong::isDefault).ifEmpty { playable }
    val tracks = if (include == null || include in visible) visible else visible + include
    return sortOrder.sort(tracks, MusicSong::title, MusicSong::releaseDate)
}

@Composable
private fun MusicResumeCard(
    model: MusicPlayerViewModel,
    catalog: MusicCatalog,
    library: MyMusic,
    versions: Boolean,
    sortOrder: MusicSortOrder,
) {
    val playback by model.playerState.collectAsStateWithLifecycle()
    val target = model.resumeTarget(catalog, library, playback) ?: return
    val song = target.song
    val album = catalog.albumsById[song.albumId]
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.secondaryContainer,
        modifier = Modifier.fillMaxWidth().clickable {
            val tracks = catalog.albumTracks(song.albumId, versions, sortOrder, include = song)
            model.resume(catalog, target, tracks)
        },
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            MusicArtwork(MusicSite.mediaUri(album?.cover)?.toString(), Modifier.size(54.dp))
            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                Text("继续播放 · ${formatMusicTime(target.positionMs)}", style = MaterialTheme.typography.labelLarge)
                Text(song.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Icon(Icons.Default.PlayArrow, "继续播放")
        }
    }
}

@Composable
private fun MusicOptionsMenu(
    sortOrder: MusicSortOrder,
    onSortChange: (MusicSortOrder) -> Unit,
    albumVersions: Boolean? = null,
    onVersionsChange: (Boolean) -> Unit = {},
    showAlbumGrid: Boolean? = null,
    onAlbumLayoutChange: (Boolean) -> Unit = {},
) {
    var expanded by remember { mutableStateOf(false) }
    var choosingSort by remember { mutableStateOf(false) }
    Box {
        PonyIconButton(
            onClick = { expanded = true },
            icon = Icons.Default.MoreVert,
            contentDescription = "更多",
        )
        MusicTopDropdownMenu(expanded, onDismissRequest = { expanded = false }) {
            if (albumVersions != null) {
                DropdownMenuItem(
                    text = { Text(if (albumVersions) "隐藏更多版本" else "显示更多版本") },
                    leadingIcon = { Icon(Icons.Default.LibraryMusic, null) },
                    colors = musicTopMenuItemColors(),
                    onClick = {
                        onVersionsChange(!albumVersions)
                        expanded = false
                    },
                )
            }
            if (showAlbumGrid != null) {
                val targetGrid = !showAlbumGrid
                DropdownMenuItem(
                    text = { Text(if (targetGrid) "宫格展示" else "列表展示") },
                    leadingIcon = {
                        Icon(if (targetGrid) Icons.Default.GridView else Icons.AutoMirrored.Filled.ViewList, null)
                    },
                    colors = musicTopMenuItemColors(),
                    onClick = {
                        onAlbumLayoutChange(targetGrid)
                        expanded = false
                    },
                )
            }
            DropdownMenuItem(
                text = {
                    Column {
                        Text("排序方式")
                        Text(sortOrder.label, style = MaterialTheme.typography.bodySmall, color = adaptivePopupMenuContentColor().copy(alpha = 0.72f))
                    }
                },
                leadingIcon = { Icon(Icons.AutoMirrored.Filled.Sort, null) },
                trailingIcon = { Icon(Icons.Default.ChevronRight, null) },
                colors = musicTopMenuItemColors(),
                onClick = {
                    expanded = false
                    choosingSort = true
                },
            )
        }
    }
    if (choosingSort) {
        PonyAlertDialog(
            title = "排序方式",
            onDismiss = { choosingSort = false },
            dismissButton = { TextButton(onClick = { choosingSort = false }) { Text("取消") } },
            content = {
                Column(Modifier.selectableGroup()) {
                    MusicSortOrder.entries.forEach { order ->
                        val selected = order == sortOrder
                        Row(
                            Modifier.fillMaxWidth().selectable(selected = selected, role = Role.RadioButton) {
                                onSortChange(order)
                                choosingSort = false
                            }.padding(vertical = 12.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = selected, onClick = null)
                            Text(order.label, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
            },
        )
    }
}

@Composable
private fun MusicTopDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        modifier = Modifier.widthIn(min = 200.dp),
        shape = RoundedCornerShape(12.dp),
        containerColor = adaptivePopupMenuContainerColor(),
        border = adaptivePopupMenuBorder(),
        tonalElevation = 2.dp,
        content = content,
    )
}

@Composable
private fun musicTopMenuItemColors(color: Color = adaptivePopupMenuContentColor()) = MenuDefaults.itemColors(
    textColor = color,
    leadingIconColor = color,
    trailingIconColor = color,
)

private fun LazyListScope.catalogFeedback(state: MusicCatalogState, model: MusicPlayerViewModel) {
    if (state.error) item { MusicMessage("曲库加载失败", "重试", model::loadCatalog) }
    else item { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
}

private fun LazyListScope.albumRail(albums: List<MusicAlbum>, state: LazyListState, open: (String) -> Unit) {
    item {
        LazyRow(state = state, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            items(albums, key = MusicAlbum::id) { album ->
                AlbumCard(album, Modifier.width(135.dp)) { open(album.id) }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AlbumCategories(
    categories: List<MusicAlbumCategory>,
    selected: MusicAlbumCategory,
    state: LazyListState,
    select: (MusicAlbumCategory) -> Unit,
) {
    Column {
        Text("分类", style = MaterialTheme.typography.titleMedium)
        LazyRow(
            state = state,
            modifier = Modifier.selectableGroup(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(categories, key = { it.name }) { category ->
                val requester = remember { BringIntoViewRequester() }
                val scope = rememberCoroutineScope()
                FilterChip(
                    selected = category == selected,
                    onClick = {
                        select(category)
                        scope.launch { requester.bringIntoView() }
                    },
                    label = { Text(category.label) },
                    modifier = Modifier.bringIntoViewRequester(requester),
                )
            }
        }
    }
}

private fun LazyListScope.albumsInGrid(
    albums: List<MusicAlbum>,
    columns: Int,
    open: (String) -> Unit,
    unavailableIds: Set<String> = emptySet(),
    albumAction: (@Composable (MusicAlbum) -> Unit)? = null,
) {
    items(albums.chunked(columns), key = { "grid:${it.first().id}" }) { row ->
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            row.forEach { album ->
                Box(Modifier.weight(1f)) {
                    val available = album.id !in unavailableIds
                    AlbumCard(
                        album,
                        Modifier.fillMaxWidth(),
                        subtitle = if (available) "${album.trackCount} 首" else "专辑暂不可用",
                        open = if (available) ({ open(album.id) }) else null,
                    )
                    if (albumAction != null) {
                        Surface(
                            Modifier.align(Alignment.TopEnd).padding(5.dp),
                            color = MaterialTheme.colorScheme.surface,
                            shape = CircleShape,
                        ) { albumAction(album) }
                    }
                }
            }
            repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

@Composable
private fun MusicSectionHeading(title: String, onViewAll: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f).padding(vertical = 7.dp))
        if (onViewAll != null) TextButton(onClick = onViewAll) { Text("查看全部") }
    }
}

@Composable
private fun MusicEmptyCollection(message: String) {
    Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun AlbumCard(
    album: MusicAlbum,
    modifier: Modifier = Modifier,
    subtitle: String = "${album.trackCount} 首",
    open: (() -> Unit)?,
) {
    Column(modifier.clickable(enabled = open != null) { open?.invoke() }.padding(bottom = 6.dp)) {
        MusicArtwork(MusicSite.mediaUri(album.cover)?.toString(), Modifier.fillMaxWidth().aspectRatio(1f), 15)
        Text(album.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 7.dp))
        Text(subtitle, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun MusicCatalog.collectionCover(ids: List<String>): String? = ids.firstNotNullOfOrNull { id ->
    songsById[id]?.let { albumsById[it.albumId]?.cover }
}

@Composable
private fun MusicCollectionRow(
    title: String,
    subtitle: String,
    cover: String?,
    blankCoverIfMissing: Boolean = false,
    open: (() -> Unit)?,
) {
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable(enabled = open != null) { open?.invoke() }.padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val artwork = MusicSite.mediaUri(cover)?.toString()
        if (blankCoverIfMissing && artwork == null) {
            Box(Modifier.size(64.dp).background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)))
        } else {
            MusicArtwork(artwork, Modifier.size(64.dp), corner = 12)
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun AlbumHeader(album: MusicAlbum, artwork: String?, tracks: List<MusicSong>) {
    val artist = tracks.mapNotNull { it.artist?.takeIf(String::isNotBlank) }.distinct().singleOrNull()
    val metadata = listOfNotNull(artist, album.releaseDate?.takeIf(String::isNotBlank)).joinToString(" · ")
    MusicCollectionHeader(album.title, artwork, metadata)
}

@Composable
private fun MusicCollectionHeader(
    title: String,
    artwork: String?,
    metadata: String,
    compactCover: Boolean = false,
    blankCoverIfMissing: Boolean = false,
) {
    val colors = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 9.dp)) {
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val coverSize = if (compactCover) (maxWidth * 0.44f).coerceAtMost(176.dp)
                else (maxWidth * 0.60f).coerceAtMost(228.dp)
            val stageSize = minOf(maxWidth, coverSize + 38.dp)
            Box(Modifier.fillMaxWidth().height(coverSize + 38.dp), contentAlignment = Alignment.Center) {
                if (blankCoverIfMissing && artwork == null) {
                    Box(Modifier.size(coverSize).background(colors.surfaceVariant, RoundedCornerShape(18.dp)))
                } else {
                    Box(
                        Modifier.size(stageSize).clip(CircleShape).background(
                            Brush.radialGradient(listOf(colors.onBackground.copy(alpha = 0.16f), Color.Transparent))
                        )
                    )
                    MusicArtwork(
                        artwork,
                        Modifier.size(coverSize).shadow(12.dp, RoundedCornerShape(18.dp)),
                        corner = 18,
                    )
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        Text(
            title,
            style = MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Bold,
            color = colors.onBackground,
        )
        if (metadata.isNotEmpty()) Text(
            metadata,
            modifier = Modifier.padding(top = 7.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = colors.onSurfaceVariant,
        )
    }
}

@Composable
private fun AlbumActions(
    trackCount: Int,
    saved: Boolean,
    canSave: Boolean,
    onPlay: () -> Unit,
    onShuffle: () -> Unit,
    onToggleSaved: () -> Unit,
) {
    val colors = MaterialTheme.colorScheme
    val canPlay = trackCount > 0
    Row(
        Modifier.fillMaxWidth().padding(bottom = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            Modifier.weight(1f).heightIn(min = 50.dp).clip(MaterialTheme.shapes.medium)
                .clickable(enabled = canPlay, role = Role.Button, onClick = onPlay),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Surface(
                modifier = Modifier.size(40.dp),
                shape = CircleShape,
                color = if (canPlay) colors.primary else colors.surfaceVariant,
                contentColor = if (canPlay) colors.onPrimary else colors.onSurfaceVariant,
            ) {
                Box(contentAlignment = Alignment.Center) { Icon(Icons.Default.PlayArrow, null) }
            }
            Column(Modifier.weight(1f)) {
                Text("全部播放", style = MaterialTheme.typography.titleSmall, color = colors.onBackground)
                Text("$trackCount 首", style = MaterialTheme.typography.labelSmall, color = colors.onSurfaceVariant)
            }
        }
        PonyIconButton(
            onClick = onShuffle, icon = Icons.Default.Shuffle, contentDescription = "随机播放",
            tint = colors.onSurfaceVariant, enabled = canPlay, size = 44.dp,
        )
        PonyIconButton(
            onClick = onToggleSaved,
            icon = if (saved) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
            contentDescription = if (saved) "取消收藏专辑" else "收藏专辑",
            tint = if (saved) colors.primary else colors.onSurfaceVariant,
            enabled = canSave,
            size = 44.dp,
        )
    }
}

@Composable
private fun PlayMusicCollection(songs: List<MusicSong>, catalog: MusicCatalog, model: MusicPlayerViewModel) {
    val playable = songs.filter { it.src != null }
    if (playable.isEmpty()) return
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        PonyButton(
            text = "全部播放",
            onClick = { model.play(playable, catalog.albumsById, playable.first().id) },
            modifier = Modifier.weight(1f),
            height = 46.dp,
            icon = { Icon(Icons.Default.PlayArrow, null) },
        )
        PonyButton(
            text = "随机播放",
            onClick = { model.play(playable, catalog.albumsById, playable.random().id, shuffled = true) },
            modifier = Modifier.weight(1f),
            style = PonyButtonStyle.Secondary,
            height = 46.dp,
            icon = { Icon(Icons.Default.Shuffle, null) },
        )
    }
}

private fun LazyListScope.musicSongs(
    ids: List<String>,
    catalog: MusicCatalog,
    library: MyMusic?,
    model: MusicPlayerViewModel,
    focus: FocusManager,
    history: Map<String, MusicHistory> = emptyMap(),
    matchedLyrics: Map<String, String> = emptyMap(),
    add: (String) -> Unit,
    remove: ((String) -> Unit)? = null,
    move: ((String, Int) -> Unit)? = null,
    showTrackNumbers: Boolean = false,
    activeTrack: Pair<String?, Boolean> = null to false,
    onPlayNext: ((MusicSong) -> Unit)? = null,
    previewCount: Int = Int.MAX_VALUE,
    onPlayed: (() -> Unit)? = null,
) {
    val queue by lazy { ids.mapNotNull { catalog.songsById[it] }.filter { it.src != null } }
    val favorites = library?.favorites.orEmpty().toSet()
    val positions = if (move != null || showTrackNumbers) ids.withIndex().associate { it.value to it.index } else emptyMap()
    items(ids.distinct().take(previewCount), key = { "track:$it" }) { id ->
        val song = catalog.songsById[id]
        val album = song?.albumId?.let { catalog.albumsById[it] }
        val record = history[id]
        val title = song?.title ?: id.substringAfterLast('/').substringBeforeLast('.')
        val resume = record?.positionMs ?: 0
        val subtitle = if (song == null) "歌曲暂不可用" else listOfNotNull(
            song.alias?.takeIf { it.isNotBlank() && it != song.title },
            if (showTrackNumbers) song.artist?.takeIf(String::isNotBlank) else album?.title,
        ).distinct().joinToString(" · ")
        val historyDetail = record?.let {
            listOfNotNull(
                "从 ${formatMusicTime(resume)} 继续".takeIf { resume > 0 && song?.src != null },
                "播放 ${it.count} 次",
                DateUtils.getRelativeTimeSpanString(it.playedAtMs, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString(),
            ).joinToString(" · ")
        }
        var menu by rememberSaveable(id) { mutableStateOf(false) }
        Row(
            Modifier.fillMaxWidth().heightIn(min = if (showTrackNumbers) 54.dp else 0.dp).clickable(enabled = song?.src != null) {
                focus.clearFocus()
                model.play(queue, catalog.albumsById, id, resume)
                onPlayed?.invoke()
            }.padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(if (onPlayNext == null) 11.dp else 6.dp),
        ) {
            if (showTrackNumbers) {
                Box(Modifier.width(26.dp), contentAlignment = Alignment.Center) {
                    if (activeTrack.first == id) MusicPlaybackIndicator(activeTrack.second)
                    else Text((positions.getValue(id) + 1).toString(), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                MusicArtwork(MusicSite.mediaUri(album?.cover)?.toString(), Modifier.size(46.dp), 9)
            }
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = if (showTrackNumbers) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleSmall,
                    maxLines = if (showTrackNumbers) 2 else 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (historyDetail != null) Text(
                    historyDetail, style = MaterialTheme.typography.labelSmall, maxLines = 1,
                    overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.primary,
                )
                matchedLyrics[id]?.takeIf(String::isNotBlank)?.let { snippet ->
                    Text(
                        "歌词匹配 · $snippet", style = MaterialTheme.typography.bodySmall, maxLines = 2,
                        overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (onPlayNext != null && song?.src != null) {
                PonyIconButton(
                    onClick = { onPlayNext(song) },
                    icon = Icons.AutoMirrored.Filled.PlaylistPlay,
                    contentDescription = "下一首播放 $title",
                    size = 38.dp,
                    iconSize = 21.dp,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (showTrackNumbers && library != null && song != null) {
                val liked = id in favorites
                PonyIconButton(
                    onClick = { model.updateLibrary(MusicCommand("favorite", songId = id, enabled = !liked)) },
                    icon = if (liked) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    contentDescription = if (liked) "取消收藏 $title" else "收藏 $title",
                    size = 38.dp,
                    iconSize = 20.dp,
                    tint = if (liked) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else if (id in favorites) {
                Icon(Icons.Default.Favorite, "已收藏", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(16.dp))
            }
            if ((library != null && song != null) || remove != null) {
                Box {
                    PonyIconButton(onClick = { menu = true }, icon = Icons.Default.MoreVert, contentDescription = "$title 的选项")
                    DropdownMenu(menu, { menu = false }) {
                        if (!showTrackNumbers && library != null && song != null && (remove == null || move != null || record != null)) {
                            DropdownMenuItem(text = { Text(if (id in favorites) "取消收藏" else "收藏") }, onClick = {
                                menu = false
                                model.updateLibrary(MusicCommand("favorite", songId = id, enabled = id !in favorites))
                            })
                        }
                        if (library != null && song != null) DropdownMenuItem(text = { Text("添加到歌单") }, onClick = { menu = false; add(id) })
                        if (remove != null) DropdownMenuItem(
                            text = { Text(when { record != null -> "删除播放记录"; move != null -> "移出歌单"; else -> "取消收藏" }) },
                            onClick = { menu = false; remove(id) },
                        )
                        if (move != null) {
                            val position = positions.getValue(id)
                            DropdownMenuItem(text = { Text("上移") }, enabled = position > 0, onClick = { menu = false; move(id, -1) })
                            DropdownMenuItem(text = { Text("下移") }, enabled = position < ids.lastIndex, onClick = { menu = false; move(id, 1) })
                        }
                    }
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.35f))
    }
}
