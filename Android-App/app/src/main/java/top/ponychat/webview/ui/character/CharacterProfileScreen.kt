package top.ponychat.webview.ui.character

import coil.compose.AsyncImage
import coil.compose.AsyncImagePainter
import androidx.compose.foundation.Image
import androidx.compose.foundation.Canvas as ComposeCanvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assignment
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Business
import androidx.compose.material.icons.filled.Campaign
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.LocalFlorist
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.RocketLaunch
import androidx.compose.material.icons.filled.Science
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.Spa
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Update
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.ScaffoldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import top.ponychat.webview.CustomToast
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.ChatScreenImagePreviewOverlay
import top.ponychat.webview.ui.common.PonyAvatar
import top.ponychat.webview.ui.common.PonyTopBar
import top.ponychat.webview.ui.common.decodeImageDataUri
import top.ponychat.webview.ui.common.resolveAvatarUrlForApi
import top.ponychat.webview.ui.theme.AccentRose
import top.ponychat.webview.ui.theme.Primary
import java.util.Locale
import kotlin.math.abs

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CharacterProfileScreen(
    character: Character,
    viewModel: CharacterViewModel,
    prefs: AppPreferences,
    onNavigateBack: () -> Unit,
    onStartChat: (Character, String) -> Unit,
    onEditSettings: (Character) -> Unit,
    onAddFromHall: (Character) -> Unit,
    embedded: Boolean = false,
) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current
    val snackbarHostState = CustomToast.current
    val scope = rememberCoroutineScope()
    fun showPrompt(message: String) {
        scope.launch { snackbarHostState.showSnackbar(message) }
    }
    val activeApiBase = prefs.effectiveApiBase()
    val fallbackApiBase = pickFallbackApiBase(activeApiBase, prefs.wanUrl, prefs.lanUrl)
    val localMatch = remember(state.characters, character) {
        state.characters.firstOrNull {
            it.id == character.id ||
                (character.sourceId?.isNotBlank() == true && it.id == character.sourceId) ||
                (it.sourceId?.isNotBlank() == true && it.sourceId == character.id) ||
                (it.contentHash?.isNotBlank() == true && it.contentHash == character.contentHash)
        }
    }
    val profile = localMatch ?: character
    val isOwned = localMatch != null
    val isSystemUser = prefs.username.trim().equals("System", ignoreCase = true)
    val canManage = isOwned && (isSystemUser || profile.isManageableLocalCharacter())
    val signature = profile.preview?.takeIf { it.isNotBlank() }
        ?: "暂无个性签名"
    val publicBio = profile.profileIntro?.takeIf { it.isNotBlank() }
        ?: profile.bio?.takeIf { it.isNotBlank() }
        ?: profile.description?.takeIf { it.isNotBlank() }
        ?: "作者还没有填写公开版角色简介。"
    val hallLikeId = profile.hallLikeId(character, state.hallCharacters)
    val hallStats = remember(state.hallCharacters, profile, character, hallLikeId) {
        state.hallCharacters.firstOrNull { hall ->
            hall.id?.isNotBlank() == true && hall.id == hallLikeId
        } ?: state.hallCharacters.firstOrNull { hall ->
            hall.matchesProfileSource(profile) || hall.matchesProfileSource(character)
        }
    }
    val displayAddedCount = hallStats?.timesAdded ?: profile.timesAdded ?: character.timesAdded ?: 0
    val displayUpdatedAt = hallStats?.updatedAt?.takeIf { it.isNotBlank() }
        ?: hallStats?.publishedAt?.takeIf { it.isNotBlank() }
        ?: profile.updatedAt?.takeIf { it.isNotBlank() }
        ?: profile.publishedAt?.takeIf { it.isNotBlank() }
        ?: character.updatedAt?.takeIf { it.isNotBlank() }
        ?: character.publishedAt.orEmpty()
    var likedToday by remember(hallLikeId, profile.likedToday, character.likedToday) {
        mutableStateOf(profile.likedToday ?: character.likedToday ?: false)
    }
    var localLikes by remember(hallLikeId, profile.likeCount, character.likeCount) {
        mutableIntStateOf(profile.likeCount ?: character.likeCount ?: 0)
    }
    val avatarPreviewUrl = remember(profile, activeApiBase) {
        resolveAvatarUrlForApi(profile.avatarUrl(), activeApiBase).orEmpty()
    }
    val profileCoverImage = remember(profile, activeApiBase, fallbackApiBase) {
        resolveProfileCoverImage(profile, activeApiBase, fallbackApiBase)
    }
    val albumImages = remember(profile, activeApiBase, fallbackApiBase) {
        resolveProfileAlbumImages(profile, activeApiBase, fallbackApiBase)
    }
    var previewImageUrl by remember { mutableStateOf<String?>(null) }
    var previewImagesForOverlay by remember { mutableStateOf<List<String>>(emptyList()) }
    var previewIndex by remember { mutableIntStateOf(0) }
    LaunchedEffect(
        character.id,
        character.sourceId,
        character.hallId,
        character.contentHash
    ) {
        viewModel.loadMyCharacters(silent = true)
        viewModel.loadCharacterHall(silent = true)
    }
    fun openPreview(images: List<String>, index: Int = 0) {
        val validImages = images.filter { it.isNotBlank() }
        if (validImages.isEmpty()) return
        previewImagesForOverlay = validImages
        previewIndex = index.coerceIn(0, validImages.lastIndex)
        previewImageUrl = validImages.getOrNull(previewIndex)
    }

    LaunchedEffect(state.actionMessage) {
        val message = state.actionMessage
        if (!message.isNullOrBlank()) {
            showPrompt(message)
            viewModel.clearActionMessage()
        }
    }

    LaunchedEffect(hallLikeId) {
        if (!hallLikeId.isNullOrBlank()) {
            viewModel.loadCharacterLikes(
                hallId = hallLikeId,
                onResult = { stats ->
                    localLikes = stats.likeCount
                    likedToday = stats.likedToday
                }
            )
        }
    }
    val handleLikeClick: () -> Unit = {
        val targetHallId = hallLikeId
        if (targetHallId.isNullOrBlank()) {
            showPrompt("此角色尚未发布到大厅")
        } else if (likedToday) {
            showPrompt("请明天再试")
        } else {
            viewModel.likeCharacter(
                hallId = targetHallId,
                onResult = { stats ->
                    localLikes = stats.likeCount
                    likedToday = stats.likedToday
                    if (stats.status == "already_liked") {
                        showPrompt(stats.message ?: "请明天再试")
                    }
                },
                onError = { message -> showPrompt(message) }
            )
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        contentWindowInsets = if (embedded) WindowInsets(0, 0, 0, 0) else ScaffoldDefaults.contentWindowInsets,
        topBar = {
            if (!embedded) PonyTopBar(
                title = "角色主页",
                onNavigateBack = onNavigateBack
            )
        },
        bottomBar = {
            if (!embedded) Surface(color = MaterialTheme.colorScheme.surface, shadowElevation = 8.dp) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    if (isOwned) {
                        Button(
                            modifier = Modifier.weight(1f),
                            onClick = { onStartChat(profile, prefs.chatMode.ifBlank { "normal" }) },
                            colors = ButtonDefaults.buttonColors(containerColor = Primary)
                        ) {
                            Text("开始聊天")
                        }
                    } else {
                        Button(
                            modifier = Modifier.weight(1f),
                            onClick = { onAddFromHall(character) },
                            colors = ButtonDefaults.buttonColors(containerColor = Primary)
                        ) {
                            Text("添加角色")
                        }
                    }
                    if (canManage) {
                        FilledTonalButton(onClick = { onEditSettings(profile) }) {
                            Text("编辑")
                        }
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
        ) {
            ProfileHero(
                character = profile,
                apiBase = activeApiBase,
                fallbackApiBase = fallbackApiBase,
                roleBadge = profileRoleBadge(profile, isOwned),
                coverImage = profileCoverImage,
                onCoverClick = {
                    if (profileCoverImage.hasImage()) {
                        openPreview(profileCoverImage.previewUrls())
                    }
                },
                onAvatarClick = {
                    if (avatarPreviewUrl.isNotBlank()) {
                        openPreview(listOf(avatarPreviewUrl))
                    }
                }
            )
            SectionBlock(title = "个性签名") {
                Text(
                    text = signature,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Medium
                )
            }
            MbtiSignatureBlock(profile)
            PopularityRow(
                addedCount = displayAddedCount,
                likeCount = localLikes,
                likedToday = likedToday,
                updatedAt = displayUpdatedAt,
                onLikeClick = handleLikeClick
            )
            if (albumImages.isNotEmpty()) {
                PhotoStrip(albumImages) { photoIndex ->
                    openPreview(albumImages.map { it.previewUrl() }, photoIndex)
                }
            }
            CharacterArchive(profile, publicBio)
            CharacterIdFooter(profile)
            Spacer(Modifier.height(if (embedded) 16.dp else 88.dp))
        }
        ChatScreenImagePreviewOverlay(
            previewImageUrl = previewImageUrl,
            previewImages = previewImagesForOverlay,
            previewIndex = previewIndex,
            onDismiss = {
                previewImageUrl = null
                previewImagesForOverlay = emptyList()
            },
            coroutineScope = scope,
            context = context
        )
    }
}

@Composable
private fun ProfileHero(
    character: Character,
    apiBase: String,
    fallbackApiBase: String,
    roleBadge: String,
    coverImage: ProfileImageSource,
    onCoverClick: () -> Unit,
    onAvatarClick: () -> Unit
) {
    val heroColors = profilePalette(character)
    Box(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(178.dp)
                .clickable { onCoverClick() }
                .background(Brush.linearGradient(heroColors))
        ) {
            if (coverImage.hasImage()) {
                ProfileFallbackImage(
                    image = coverImage,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 126.dp, start = 20.dp, end = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Surface(
                modifier = Modifier.clickable { onAvatarClick() },
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 6.dp
            ) {
                PonyAvatar(
                    avatarUrl = character.avatarUrl(),
                    name = character.displayName(),
                    apiBase = apiBase,
                    fallbackApiBase = fallbackApiBase,
                    size = 92,
                    modifier = Modifier.padding(4.dp)
                )
            }
            Spacer(Modifier.height(12.dp))
            Text(
                text = character.displayName(),
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onBackground,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            if (character.isCertifiedProfile()) {
                CertifiedCharacterBadge()
            } else {
                val ownerLine = "by ${characterProfileOwner(character)}" +
                    roleBadge.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()
                Text(
                    text = ownerLine,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (character.safeTags().isNotEmpty()) {
                LazyRow(
                    modifier = Modifier.padding(top = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = PaddingValues(horizontal = 4.dp)
                ) {
                    items(character.safeTags().take(6)) { tag ->
                        Surface(
                            shape = RoundedCornerShape(999.dp),
                            color = Primary.copy(alpha = 0.12f)
                        ) {
                            Text(
                                text = tag,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                style = MaterialTheme.typography.labelMedium,
                                color = Primary
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CertifiedCharacterBadge() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Spacer(Modifier.width(22.dp))
        Text(
            text = CertifiedCharacterLabel,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.width(4.dp))
        CertifiedOctagonIcon()
    }
}

@Composable
private fun CertifiedOctagonIcon(modifier: Modifier = Modifier) {
    ComposeCanvas(
        modifier = modifier
            .size(18.dp)
            .semantics { contentDescription = "认证" }
    ) {
        val side = size.minDimension
        fun p(x: Float, y: Float) = Offset(side * x / 24f, side * y / 24f)
        val badge = Path().apply {
            moveTo(p(12f, 1.5f).x, p(12f, 1.5f).y)
            listOf(
                p(15.1f, 4.2f),
                p(19.2f, 4.8f),
                p(19.8f, 8.9f),
                p(22.5f, 12f),
                p(19.8f, 15.1f),
                p(19.2f, 19.2f),
                p(15.1f, 19.8f),
                p(12f, 22.5f),
                p(8.9f, 19.8f),
                p(4.8f, 19.2f),
                p(4.2f, 15.1f),
                p(1.5f, 12f),
                p(4.2f, 8.9f),
                p(4.8f, 4.8f),
                p(8.9f, 4.2f),
            ).forEach { lineTo(it.x, it.y) }
            close()
        }
        drawPath(path = badge, color = Primary)

        val check = Path().apply {
            moveTo(side * 7.4f / 24f, side * 12.2f / 24f)
            lineTo(side * 10.4f / 24f, side * 15.3f / 24f)
            lineTo(side * 16.8f / 24f, side * 8.5f / 24f)
        }
        drawPath(
            path = check,
            color = Color.White,
            style = Stroke(
                width = side * 2.35f / 24f,
                cap = StrokeCap.Round,
                join = StrokeJoin.Round
            )
        )
    }
}

@Composable
private fun SectionBlock(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 10.dp)
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(bottom = 8.dp)
        )
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.48f)
        ) {
            Column(modifier = Modifier.padding(14.dp), content = content)
        }
    }
}

@Composable
private fun MbtiSignatureBlock(character: Character) {
    val mbti = mbtiProfileOption(character.profileMbti.orEmpty()) ?: return
    val visual = mbtiVisualStyle(mbti.code)
    val isDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val accent = if (isDark) visual.darkAccent else visual.lightAccent
    val base = if (isDark) Color(0xFF161D2B) else Color(0xFFF8FAFC)
    val cardColor = blendColors(accent, base, 0.18f)
    val circleColor = blendColors(accent, base, 0.18f)
    val titleColor = accent
    val subtitleColor = if (isDark) {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.82f)
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        shape = RoundedCornerShape(12.dp),
        color = cardColor,
        border = BorderStroke(1.dp, accent.copy(alpha = 0.78f))
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 18.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "${mbti.code} · ${mbti.name}",
                    style = MaterialTheme.typography.titleLarge,
                    color = titleColor,
                    fontWeight = FontWeight.Bold
                )
                Spacer(Modifier.height(3.dp))
                Text(
                    text = mbti.traits,
                    style = MaterialTheme.typography.bodySmall,
                    color = subtitleColor
                )
            }
            Surface(
                modifier = Modifier.size(44.dp),
                shape = CircleShape,
                color = circleColor,
                border = BorderStroke(1.dp, accent.copy(alpha = 0.78f))
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = visual.icon,
                        contentDescription = null,
                        tint = accent,
                        modifier = Modifier.size(23.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun PopularityRow(
    addedCount: Int,
    likeCount: Int,
    likedToday: Boolean,
    updatedAt: String,
    onLikeClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        StatTile(
            label = "喜欢",
            value = compactCount(likeCount),
            icon = if (likedToday) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
            iconTint = AccentRose,
            modifier = Modifier.weight(1f),
            onClick = onLikeClick
        )
        StatTile(
            label = "添加",
            value = compactCount(addedCount),
            icon = Icons.Filled.PersonAdd,
            iconTint = Primary,
            modifier = Modifier.weight(1f)
        )
        StatTile(
            label = "最近更新",
            value = compactDate(updatedAt),
            icon = Icons.Filled.Update,
            iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun StatTile(
    label: String,
    value: String,
    icon: ImageVector,
    iconTint: Color,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null
) {
    Surface(
        modifier = modifier.then(if (onClick != null) Modifier.clickable { onClick() } else Modifier),
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    ) {
        Column(
            modifier = Modifier.padding(vertical = 10.dp, horizontal = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = iconTint,
                modifier = Modifier.size(19.dp)
            )
            Spacer(Modifier.height(4.dp))
            Text(value, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun PhotoStrip(
    photoImages: List<ProfileImageSource>,
    onPhotoClick: (Int) -> Unit
) {
    val photoHeight = 168.dp
    Column(modifier = Modifier.padding(vertical = 10.dp)) {
        Text(
            text = "相册",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
        )
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(horizontal = 16.dp)
        ) {
            items(photoImages.withIndex().toList()) { item ->
                val photoIndex = item.index
                AdaptiveAlbumPhoto(
                    image = item.value,
                    height = photoHeight,
                    modifier = Modifier.clickable { onPhotoClick(photoIndex) }
                )
            }
        }
    }
}

@Composable
private fun AdaptiveAlbumPhoto(
    image: ProfileImageSource,
    height: androidx.compose.ui.unit.Dp,
    modifier: Modifier = Modifier
) {
    var aspectRatio by remember(image) { mutableFloatStateOf(132f / 168f) }
    val targetWidth = (height.value * aspectRatio.coerceIn(0.2f, 4f)).dp
    Box(
        modifier = modifier
            .width(targetWidth)
            .height(height)
            .clip(RoundedCornerShape(14.dp))
            .background(Color.White),
        contentAlignment = Alignment.Center
    ) {
        ProfileFallbackImage(
            image = image,
            contentDescription = null,
            contentScale = ContentScale.Fit,
            onSuccess = { success ->
                val drawable = success.result.drawable
                val w = drawable.intrinsicWidth
                val h = drawable.intrinsicHeight
                if (w > 0 && h > 0) {
                    aspectRatio = (w.toFloat() / h.toFloat()).coerceIn(0.2f, 4f)
                }
            },
            modifier = Modifier.fillMaxSize()
        )
    }
}

@Composable
private fun ProfileFallbackImage(
    image: ProfileImageSource,
    contentDescription: String?,
    contentScale: ContentScale,
    modifier: Modifier = Modifier,
    onSuccess: ((AsyncImagePainter.State.Success) -> Unit)? = null
) {
    var useFallback by remember(image) { mutableStateOf(false) }
    val fallbackUrl = image.fallbackUrl
    val model = if (useFallback && !fallbackUrl.isNullOrBlank()) {
        fallbackUrl
    } else {
        image.primaryUrl
    }
    if (model.isBlank()) return
    val dataUriBitmap = remember(model) { decodeImageDataUri(model) }
    if (dataUriBitmap != null) {
        Image(
            bitmap = dataUriBitmap.asImageBitmap(),
            contentDescription = contentDescription,
            contentScale = contentScale,
            modifier = modifier
        )
        return
    }
    AsyncImage(
        model = model,
        contentDescription = contentDescription,
        contentScale = contentScale,
        onSuccess = onSuccess,
        onError = {
            if (!useFallback && !fallbackUrl.isNullOrBlank()) {
                useFallback = true
            }
        },
        modifier = modifier
    )
}

@Composable
private fun CharacterArchive(character: Character, publicBio: String) {
    val mbti = mbtiProfileOption(character.profileMbti.orEmpty())
    SectionBlock("角色档案") {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            ArchiveTile("种族", character.profileSpecies.cleanProfileValue(), Modifier.weight(1f))
            ArchiveTile("性别", character.profileGender.cleanProfileValue(), Modifier.weight(1f))
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            ArchiveTile("年龄", character.profileAge.cleanProfileValue(), Modifier.weight(1f))
            ArchiveTile("16人格", mbti?.let { "${it.code} ${it.name}" } ?: "未设置", Modifier.weight(1f))
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            ArchiveTile("性格", character.profilePersonality.cleanProfileValue(), Modifier.weight(1f))
            ArchiveTile("兴趣", character.profileInterests.cleanProfileValue(), Modifier.weight(1f))
        }
        Spacer(Modifier.height(14.dp))
        Text(
            text = "简介",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = publicBio,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            lineHeight = MaterialTheme.typography.bodyMedium.lineHeight
        )
    }
}

@Composable
private fun CharacterIdFooter(character: Character) {
    val localId = character.id?.trim()?.takeIf { it.isNotBlank() } ?: return
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "角色ID：$localId",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.42f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun ArchiveTile(label: String, value: String, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(5.dp))
            Text(
                value,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Medium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

private const val CertifiedCharacterLabel = "认证角色"

private fun characterProfileOwner(character: Character): String =
    character.publicOwner?.trim()?.takeIf { it.isNotBlank() }
        ?: character.addedFrom?.trim()?.takeIf { it.isNotBlank() }
        ?: "System".takeIf { character.isOfficialReferenceProfile() }
        ?: character.ownerRaw?.trim()?.takeIf { it.isNotBlank() }
        ?: character.owner?.trim()?.takeIf { it.isNotBlank() }
        ?: "匿名作者"

private fun String?.cleanProfileValue(): String =
    this?.trim()?.takeIf { it.isNotBlank() } ?: "未设置"

private fun profileRoleBadge(character: Character, isOwned: Boolean): String =
    when {
        character.isCertifiedProfile() -> CertifiedCharacterLabel
        character.isPublic -> "大厅角色"
        isOwned -> ""
        else -> "角色"
    }

private fun Character.isCertifiedProfile(): Boolean =
    isSystemPublished() || isOfficialReferenceProfile()

private fun Character.isOfficialReferenceProfile(): Boolean =
    isOfficialReference || officialSourceId?.isNotBlank() == true

private fun Character.isManageableLocalCharacter(): Boolean {
    if (sourceId?.isNotBlank() == true) return false
    if (isLockedOfficialReference()) return false
    return canEdit
}

private fun compactCount(value: Int): String =
    when {
        value >= 10000 -> String.format(Locale.US, "%.1fw", value / 10000f)
        value >= 1000 -> String.format(Locale.US, "%.1fk", value / 1000f)
        else -> value.toString()
    }

private fun compactDate(raw: String): String {
    if (raw.isBlank()) return "今天"
    return raw.take(10).ifBlank { "今天" }
}

private data class MbtiProfileOption(val code: String, val name: String, val traits: String)

private data class MbtiVisualStyle(
    val darkAccent: Color,
    val lightAccent: Color,
    val icon: ImageVector
)

private val mbtiProfileOptions = listOf(
    MbtiProfileOption("INTJ", "建筑师", "战略 / 独立 / 洞察"),
    MbtiProfileOption("INTP", "逻辑学家", "理性 / 好奇 / 分析"),
    MbtiProfileOption("ENTJ", "指挥官", "果断 / 目标感 / 领导"),
    MbtiProfileOption("ENTP", "辩论家", "机敏 / 创意 / 挑战"),
    MbtiProfileOption("INFJ", "提倡者", "理想 / 共情 / 深刻"),
    MbtiProfileOption("INFP", "调停者", "温柔 / 理想主义 / 共情"),
    MbtiProfileOption("ENFJ", "主人公", "热忱 / 鼓舞 / 亲和"),
    MbtiProfileOption("ENFP", "竞选者", "自由 / 热情 / 想象力"),
    MbtiProfileOption("ISTJ", "物流师", "可靠 / 秩序 / 负责"),
    MbtiProfileOption("ISFJ", "守卫者", "体贴 / 稳定 / 守护"),
    MbtiProfileOption("ESTJ", "总经理", "务实 / 组织 / 执行"),
    MbtiProfileOption("ESFJ", "执政官", "友善 / 照顾 / 合群"),
    MbtiProfileOption("ISTP", "鉴赏家", "冷静 / 动手 / 灵活"),
    MbtiProfileOption("ISFP", "探险家", "敏感 / 审美 / 自由"),
    MbtiProfileOption("ESTP", "企业家", "行动 / 直接 / 冒险"),
    MbtiProfileOption("ESFP", "表演者", "活泼 / 感受力 / 快乐")
)

private fun mbtiProfileOption(code: String): MbtiProfileOption? =
    mbtiProfileOptions.firstOrNull { it.code == code.trim().uppercase() }

private fun mbtiVisualStyle(code: String): MbtiVisualStyle {
    val normalized = code.trim().uppercase()
    val analyst = MbtiVisualStyle(
        darkAccent = Color(0xFF9F80FF),
        lightAccent = Color(0xFF9C7AFF),
        icon = when (normalized) {
            "INTJ" -> Icons.Filled.Business
            "INTP" -> Icons.Filled.Science
            "ENTJ" -> Icons.Filled.Flag
            "ENTP" -> Icons.Filled.Forum
            else -> Icons.Filled.Business
        }
    )
    val diplomat = MbtiVisualStyle(
        darkAccent = Color(0xFF86EFAC),
        lightAccent = Color(0xFF16A74B),
        icon = when (normalized) {
            "INFJ" -> Icons.Filled.Spa
            "INFP" -> Icons.Filled.LocalFlorist
            "ENFJ" -> Icons.Filled.AutoAwesome
            "ENFP" -> Icons.Filled.Campaign
            else -> Icons.Filled.Spa
        }
    )
    val sentinel = MbtiVisualStyle(
        darkAccent = Color(0xFF67E8F9),
        lightAccent = Color(0xFF079FB4),
        icon = when (normalized) {
            "ISTJ" -> Icons.Filled.Assignment
            "ISFJ" -> Icons.Filled.Shield
            "ESTJ" -> Icons.Filled.BarChart
            "ESFJ" -> Icons.Filled.Groups
            else -> Icons.Filled.Assignment
        }
    )
    val explorer = MbtiVisualStyle(
        darkAccent = Color(0xFFFACC15),
        lightAccent = Color(0xFFC98208),
        icon = when (normalized) {
            "ISTP" -> Icons.Filled.Build
            "ISFP" -> Icons.Filled.Palette
            "ESTP" -> Icons.Filled.RocketLaunch
            "ESFP" -> Icons.Filled.MusicNote
            else -> Icons.Filled.Build
        }
    )
    return when (normalized) {
        "INTJ", "INTP", "ENTJ", "ENTP" -> analyst
        "INFJ", "INFP", "ENFJ", "ENFP" -> diplomat
        "ISTJ", "ISFJ", "ESTJ", "ESFJ" -> sentinel
        "ISTP", "ISFP", "ESTP", "ESFP" -> explorer
        else -> analyst
    }
}

private fun blendColors(foreground: Color, background: Color, foregroundAlpha: Float): Color {
    val alpha = foregroundAlpha.coerceIn(0f, 1f)
    return Color(
        red = foreground.red * alpha + background.red * (1f - alpha),
        green = foreground.green * alpha + background.green * (1f - alpha),
        blue = foreground.blue * alpha + background.blue * (1f - alpha),
        alpha = 1f
    )
}

private fun profilePalette(character: Character): List<Color> {
    val palettes = listOf(
        listOf(Color(0xFF6D8DF7), Color(0xFFE99BB2), Color(0xFFFFC857)),
        listOf(Color(0xFF2EC4B6), Color(0xFF5E60CE), Color(0xFFFFD166)),
        listOf(Color(0xFFFF7A59), Color(0xFF7BD389), Color(0xFF4D96FF)),
        listOf(Color(0xFF8E7CFF), Color(0xFFFF9FAD), Color(0xFF6EE7B7))
    )
    return palettes[abs(character.stableId().hashCode()) % palettes.size]
}

private fun Character.hallLikeId(source: Character, hallCharacters: List<Character>): String? =
    hallId?.takeIf { it.isNotBlank() }
        ?: source.hallId?.takeIf { it.isNotBlank() }
        ?: source.sourceId?.takeIf { it.isNotBlank() }
        ?: sourceId?.takeIf { it.isNotBlank() }
        ?: source.id?.takeIf { id -> hallCharacters.any { it.id == id } }
        ?: hallCharacters.firstOrNull { it.matchesProfileSource(this) || it.matchesProfileSource(source) }
            ?.id
            ?.takeIf { it.isNotBlank() }

private fun Character.matchesProfileSource(source: Character): Boolean {
    val hallEntryId = id?.takeIf { it.isNotBlank() }
    if (hallEntryId != null) {
        if (hallEntryId == source.hallId || hallEntryId == source.sourceId || hallEntryId == source.originalId) {
            return true
        }
    }
    val hash = contentHash?.takeIf { it.isNotBlank() }
    val sourceHash = source.contentHash?.takeIf { it.isNotBlank() }
        ?: source.sourceContentHash?.takeIf { it.isNotBlank() }
    if (hash != null && hash == sourceHash) {
        return true
    }
    val officialSource = officialSourceId?.takeIf { it.isNotBlank() }
    return officialSource != null && officialSource == source.officialSourceId
}

private data class ProfileImageSource(
    val primaryUrl: String,
    val fallbackUrl: String? = null
) {
    fun hasImage(): Boolean = primaryUrl.isNotBlank() || !fallbackUrl.isNullOrBlank()

    fun previewUrl(): String = primaryUrl.ifBlank { fallbackUrl.orEmpty() }

    fun previewUrls(): List<String> =
        listOf(primaryUrl, fallbackUrl.orEmpty()).filter { it.isNotBlank() }.distinct()
}

private fun resolveProfileCoverImage(
    character: Character,
    apiBase: String,
    fallbackApiBase: String
): ProfileImageSource =
    character.profileCover
        ?.takeIf { it.isNotBlank() }
        ?.let { resolveProfileImageSource(it, apiBase, fallbackApiBase) }
        ?: ProfileImageSource("")

private fun resolveProfileAlbumImages(
    character: Character,
    apiBase: String,
    fallbackApiBase: String
): List<ProfileImageSource> =
    character.safeProfilePhotos()
        .map { resolveProfileImageSource(it, apiBase, fallbackApiBase) }
        .filter { it.hasImage() }

private fun resolveProfileImageSource(
    url: String,
    apiBase: String,
    fallbackApiBase: String
): ProfileImageSource {
    val primary = resolveProfileImageUrl(url, apiBase)
    val fallback = resolveProfileImageUrl(url, fallbackApiBase)
        .takeIf { it.isNotBlank() && it != primary }
    return ProfileImageSource(primaryUrl = primary, fallbackUrl = fallback)
}

private fun resolveProfileImageUrl(url: String, apiBase: String): String {
    val trimmed = url.trim()
    if (trimmed.isBlank() || trimmed.startsWith("data:") || trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
        return trimmed
    }
    val base = apiBase.trimEnd('/')
    return if (trimmed.startsWith("/")) "$base$trimmed" else "$base/$trimmed"
}
