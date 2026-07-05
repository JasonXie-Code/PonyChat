<template>
  <div class="section-root">
    <p v-if="error" class="card card--error">{{ error }}</p>
    <div v-else class="card card-fill">
      <div class="toolbar">
        <span class="muted">共 {{ groupedList.length }} 个角色（合并 {{ referenceTotal }} 个引用）</span>
        <div class="toolbar-right">
          <input v-model="search" class="search-input" placeholder="搜索名称 / ID / 创建者 / 引用用户 / 角色签名 / 标签…" />
          <button type="button" class="btn btn-primary" @click="openCreate">创建角色</button>
          <button type="button" class="btn" @click="load">刷新</button>
        </div>
      </div>

      <div
        ref="listViewportRef"
        class="char-list-viewport admin-grid-list"
        :style="
          gridVars({
            '--cw-name': 'name',
            '--cw-creator': 'creator',
            '--cw-id': 'id',
            '--cw-visible': 'visible',
            '--cw-bio': 'bio',
          })
        "
      >
        <!-- 列表表头 -->
        <div class="list-head admin-grid-head">
          <span class="col-av"></span>
          <span class="col-name th-sortable th-resizable" @click="toggleSort('name')">
            名称 {{ sortIcon('name') }}
            <span
              class="col-resizer"
              @mousedown.stop="(e) => startResize('name', e, e.currentTarget.parentElement)"
              @click.stop
            />
          </span>
          <span class="col-creator th-sortable th-resizable" @click="toggleSort('creator')">
            创建者 {{ sortIcon('creator') }}
            <span
              class="col-resizer"
              @mousedown.stop="(e) => startResize('creator', e, e.currentTarget.parentElement)"
              @click.stop
            />
          </span>
          <span class="col-id th-sortable th-resizable" @click="toggleSort('id')">
            ID {{ sortIcon('id') }}
            <span
              class="col-resizer"
              @mousedown.stop="(e) => startResize('id', e, e.currentTarget.parentElement)"
              @click.stop
            />
          </span>
          <span class="col-visible th-resizable">
            <button
              type="button"
              class="visibility-filter-btn"
              :class="`visibility-filter-btn--${visibilityFilter}`"
              :title="visibilityFilterTitle"
              @click="cycleVisibilityFilter"
            >
              {{ visibilityFilterLabel }}
            </button>
            <span
              class="col-resizer"
              @mousedown.stop="(e) => startResize('visible', e, e.currentTarget.parentElement)"
              @click.stop
            />
          </span>
          <span class="col-pub th-sortable" @click="toggleSort('pub')">公开 {{ sortIcon('pub') }}</span>
          <span class="col-web th-sortable" @click="toggleSort('web')">网页 {{ sortIcon('web') }}</span>
          <span class="col-voice th-sortable" @click="toggleSort('voice')">语音 {{ sortIcon('voice') }}</span>
          <span class="col-bio th-sortable th-resizable" @click="toggleSort('bio')">
            角色签名 {{ sortIcon('bio') }}
            <span
              class="col-resizer"
              @mousedown.stop="(e) => startResize('bio', e, e.currentTarget.parentElement)"
              @click.stop
            />
          </span>
          <span class="col-act">操作</span>
        </div>

        <!-- 列表行 -->
        <div class="list-body admin-grid-body">
          <div v-for="c in pagedItems" :key="c.id" class="list-row admin-grid-row">
          <!-- 头像 -->
          <div class="col-av">
            <img
              v-if="c.avatar && !avatarFailed[c.id]"
              :src="avatarUrl(c.avatar)"
              class="av"
              alt=""
              loading="lazy"
              @error="avatarFailed[c.id] = true"
            />
            <div v-else class="av ph">{{ (c.name || '?')[0] }}</div>
          </div>
          <!-- 名称 -->
          <div class="col-name fw">
            <span>{{ c.name || c.id }}</span>
            <span v-if="c.referenceCount" class="ref-chip">引用 {{ c.referenceCount }}</span>
          </div>
          <!-- 创建者 -->
          <div class="col-creator muted small">{{ c.creator || '—' }}</div>
          <!-- ID -->
          <div class="col-id mono small muted ellipsis" :title="c.id">{{ c.id || '—' }}</div>
          <!-- 用户可见 -->
          <div class="col-visible">
            <span :class="c.isUserVisible ? 'badge-on' : 'badge-off'">{{ c.isUserVisible ? '是' : '否' }}</span>
          </div>
          <!-- 公开 -->
          <div class="col-pub">
            <span :class="c.isPublic ? 'badge-on' : 'badge-off'">{{ c.isPublic ? '是' : '否' }}</span>
          </div>
          <!-- 网页 -->
          <div class="col-web">
            <span :class="c.isWebVisible ? 'badge-web' : 'badge-off'">{{ c.isWebVisible ? '是' : '否' }}</span>
          </div>
          <!-- 语音 -->
          <div class="col-voice">
            <span :class="isVoiceEnabled(c) ? 'badge-on' : 'badge-off'">{{ isVoiceEnabled(c) ? '启用' : '关闭' }}</span>
          </div>
          <!-- 角色签名 -->
          <div class="col-bio small muted ellipsis" :title="c.signature || c.bio">{{ signaturePreview(c) }}</div>
          <!-- 操作 -->
          <div class="col-act">
            <button type="button" class="btn btn-sm" @click="openEdit(c)">编辑</button>
            <button type="button" class="btn btn-sm btn-danger" @click="onDelete(c)">删除</button>
          </div>
        </div>
        </div>
      </div>

      <AdminPager
        :page="page"
        :total-pages="totalPages"
        :total="total"
        :page-size="pageSize"
        @prev="prev"
        @next="next"
      />
    </div>

    <!-- 编辑弹层 -->
    <Teleport to="body">
      <div
        v-if="editOpen"
        class="modal-mask admin-shell"
        role="dialog"
        aria-modal="true"
        @mousedown="onBackdropMouseDown"
        @click.self="onBackdropClickSelf"
      >
        <div class="modal card">
          <header class="modal-header">
            <div class="modal-header-left">
              <h3 class="modal-title">编辑角色</h3>
              <p class="modal-id">ID: {{ editForm.id }}</p>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="closeEdit">×</button>
          </header>
          <div class="modal-body modal-body-grid">
            <section class="form-panel">
              <h4 class="form-panel-title">基础信息</h4>
              <div class="ownership-panel">
                <div class="ownership-grid">
                  <div>
                    <span>创建者</span>
                    <strong>{{ editMeta.creator || '—' }}</strong>
                  </div>
                  <div>
                    <span>创建时间</span>
                    <strong>{{ fmtMetaTime(editMeta.createdAt) }}</strong>
                  </div>
                  <div>
                    <span>引用数量</span>
                    <strong>{{ editMeta.referenceCount }}</strong>
                  </div>
                </div>
                <div v-if="editMeta.referenceRows.length" class="reference-box">
                  <div class="reference-title">引用情况</div>
                  <div class="reference-list">
                    <div v-for="r in editMeta.referenceRows" :key="r.id" class="reference-row">
                      <span class="reference-owner">{{ r.owner || '—' }}</span>
                      <span class="reference-id mono">{{ r.id }}</span>
                      <button
                        type="button"
                        class="reference-visibility-btn"
                        :class="r.isUserVisible ? 'badge-on' : 'badge-off'"
                        :title="r.isUserVisible ? '点击后隐藏' : '点击后设为可见'"
                        @click="toggleReferenceVisibility(r)"
                      >
                        {{ r.isUserVisible ? '可见' : '隐藏' }}
                      </button>
                      <span v-if="r.isSourceOwner" class="source-owner-chip">主角色</span>
                      <button v-else type="button" class="btn btn-xs btn-danger" @click="cancelReference(r)">取消引用</button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="fld fld-avatar">
                <span class="fld-avatar-label">头像</span>
                <div class="avatar-edit-row">
                  <div class="avatar-preview-box">
                    <img
                      v-if="editForm.avatar && !editAvatarFailed"
                      :src="avatarUrl(editForm.avatar)"
                      alt=""
                      class="avatar-preview-lg"
                      @error="editAvatarFailed = true"
                    />
                    <div v-else class="avatar-preview-ph-lg">{{ avatarPreviewLetter }}</div>
                  </div>
                  <div class="avatar-edit-actions">
                    <input
                      ref="avatarFileRef"
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/gif"
                      class="avatar-file-input"
                      @change="onAvatarFileChange"
                    />
                    <button
                      type="button"
                      class="btn btn-sm btn-avatar-upload"
                      :disabled="avatarUploading"
                      @click="triggerAvatarPick"
                    >
                      {{ avatarUploading ? '上传中…' : '上传新头像' }}
                    </button>
                  </div>
                </div>
              </div>
              <label class="fld">
                <span>名称</span>
                <input v-model="editForm.name" type="text" placeholder="角色名称" />
              </label>
              <label class="fld">
                <span>角色 ID</span>
                <input v-model="editForm.newId" class="mono" type="text" placeholder="例如 twilight_sparkle" spellcheck="false" />
              </label>
              <label class="fld">
                <span>个性签名</span>
                <textarea v-model="editForm.signature" rows="3" placeholder="展示在角色主页上的短介绍" />
              </label>
              <label class="fld">
                <span>标签</span>
                <input v-model="editForm.tags" type="text" placeholder="用逗号分隔" />
              </label>
              <label class="fld fld-last">
                <span>角色设定</span>
                <textarea v-model="editForm.persona" rows="8" placeholder="角色提示词、背景、说话方式等" />
              </label>
            </section>

            <section class="form-panel">
              <h4 class="form-panel-title">角色档案</h4>
              <label class="fld">
                <span>种族</span>
                <input v-model="editForm.profileSpecies" type="text" placeholder="例如 飞马 / 人类 / 精灵" />
              </label>
              <label class="fld">
                <span>性别</span>
                <input v-model="editForm.profileGender" type="text" placeholder="例如 女性 / 雌性 / 男性" />
              </label>
              <label class="fld">
                <span>年龄</span>
                <input v-model="editForm.profileAge" type="text" placeholder="例如 22岁 / 成年 / 青少年" />
              </label>
              <label class="fld">
                <span>16人格</span>
                <div ref="editMbtiSelectRef" class="pony-select" :class="{ open: editMbtiMenuOpen }">
                  <button type="button" class="pony-select-trigger" @click.stop="editMbtiMenuOpen = !editMbtiMenuOpen">
                    <span>{{ mbtiLabel(editForm.profileMbti) }}</span>
                    <span class="pony-select-arrow">⌄</span>
                  </button>
                  <div v-if="editMbtiMenuOpen" class="pony-select-menu">
                    <button
                      type="button"
                      class="pony-select-option"
                      :class="{ selected: !editForm.profileMbti }"
                      @click="chooseEditMbti('')"
                    >
                      <span class="pony-select-code">--</span>
                      <span class="pony-select-text">
                        <b>不展示</b>
                        <small>角色主页不显示 16 人格</small>
                      </span>
                      <span v-if="!editForm.profileMbti" class="pony-select-check">✓</span>
                    </button>
                    <button
                      v-for="item in mbtiOptions"
                      :key="item.code"
                      type="button"
                      class="pony-select-option"
                      :class="{ selected: editForm.profileMbti === item.code }"
                      @click="chooseEditMbti(item.code)"
                    >
                      <span class="pony-select-code">{{ item.code }}</span>
                      <span class="pony-select-text">
                        <b>{{ item.name }}</b>
                        <small>{{ item.desc }}</small>
                      </span>
                      <span v-if="editForm.profileMbti === item.code" class="pony-select-check">✓</span>
                    </button>
                  </div>
                </div>
              </label>
              <label class="fld">
                <span>性格</span>
                <input v-model="editForm.profilePersonality" type="text" placeholder="例如 温柔、好奇、认真" />
              </label>
              <label class="fld">
                <span>兴趣</span>
                <input v-model="editForm.profileInterests" type="text" placeholder="例如 阅读、甜点、冒险" />
              </label>
              <label class="fld fld-last">
                <span>简介</span>
                <textarea v-model="editForm.profileIntro" rows="3" placeholder="公开角色简介，会作为角色档案的一部分带入角色设定" />
              </label>

              <h4 class="form-panel-title form-panel-title-spaced">角色主页素材</h4>
              <div class="fld">
                <span>封面</span>
                <div class="cover-grid">
                  <div v-if="editForm.profileCover" class="cover-item">
                    <img :src="avatarUrl(editForm.profileCover)" alt="" />
                    <button type="button" class="photo-remove" @click="removeEditCover">×</button>
                  </div>
                  <button v-else type="button" class="cover-add" :disabled="profileImageUploading" @click="triggerEditCoverPick">
                    +
                  </button>
                </div>
                <input
                  ref="editCoverFileRef"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  class="avatar-file-input"
                  @change="(e) => onProfileImagePick(e, 'editCover')"
                />
              </div>
              <div class="fld">
                <span>相册</span>
                <div class="photo-grid">
                  <div v-for="(photo, index) in editForm.profilePhotos" :key="`${photo}-${index}`" class="photo-item">
                    <img :src="avatarUrl(photo)" alt="" />
                    <button type="button" class="photo-remove" @click="removeEditPhoto(index)">×</button>
                  </div>
                  <button type="button" class="photo-add" :disabled="profileImageUploading || editForm.profilePhotos.length >= 12" @click="triggerEditPhotosPick">
                    +
                  </button>
                </div>
                <input
                  ref="editPhotosFileRef"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  class="avatar-file-input"
                  @change="(e) => onProfileImagePick(e, 'editPhotos')"
                />
              </div>

              <h4 class="form-panel-title form-panel-title-spaced">角色音色</h4>
              <div class="fld row-inline">
                <PonyCheckbox v-model="editForm.voiceEnabled">启用语音消息</PonyCheckbox>
              </div>
              <div class="fld">
                <span>音色来源</span>
                <div class="voice-source-tabs">
                  <button type="button" :class="{ active: editForm.voiceSourceMode === 'voice_id' }" @click="setVoiceSource(editForm, 'voice_id')">Voice ID</button>
                  <button type="button" :class="{ active: editForm.voiceSourceMode === 'instruct' }" @click="setVoiceSource(editForm, 'instruct')">描述</button>
                  <button type="button" :class="{ active: editForm.voiceSourceMode === 'clone' }" @click="setVoiceSource(editForm, 'clone')">参考音频</button>
                </div>
              </div>
              <label v-if="editForm.voiceSourceMode === 'voice_id'" class="fld">
                <span>Voice ID</span>
                <input v-model="editForm.voiceId" class="mono" type="text" placeholder="例如 qwen3tts:紫悦" spellcheck="false" />
              </label>
              <template v-else-if="editForm.voiceSourceMode === 'instruct'">
                <label class="fld">
                  <span>音色描述</span>
                  <textarea v-model="editForm.voiceInstruct" rows="3" placeholder="例如 清亮、轻快、靠近手机麦克风，语气自然" />
                </label>
                <div class="voice-action-row">
                  <button type="button" class="btn btn-sm" :disabled="voiceDesignBusy" @click="previewDesignVoice(editForm)">{{ voiceDesignBusy ? '生成中…' : '试听' }}</button>
                  <button type="button" class="btn btn-sm btn-primary" :disabled="voiceDesignBusy" @click="replaceDesignVoice(editForm)">{{ voiceDesignBusy ? '生成中…' : '更换' }}</button>
                </div>
              </template>
              <template v-else>
                <div class="fld row-inline">
                  <span>参考音频</span>
                  <button type="button" class="btn btn-sm btn-primary" :disabled="voiceReferenceUploading" @click="triggerVoiceAudioPick('edit')">
                    {{ voiceReferenceUploading ? '上传中…' : '上传' }}
                  </button>
                  <small class="voice-file-name">{{ editForm.voiceReferenceAudioUrl ? editForm.voiceReferenceAudioUrl.split('/').pop() : '未上传' }}</small>
                </div>
                <input ref="editVoiceAudioFileRef" type="file" accept="audio/*" class="avatar-file-input" @change="(e) => onVoiceAudioPick(e, editForm)" />
                <label class="fld">
                  <span>音频文本</span>
                  <textarea v-model="editForm.voiceReferenceText" rows="3" placeholder="逐字填写参考音频中说出的内容" />
                </label>
                <label class="fld">
                  <span>附加指令</span>
                  <textarea v-model="editForm.voiceInstruct" rows="2" placeholder="可选：描述语速、情绪、距离感" />
                </label>
              </template>

              <h4 class="form-panel-title form-panel-title-spaced">发布状态</h4>
              <div class="fld row-inline">
                <PonyCheckbox v-model="editForm.isUserVisible">用户可见</PonyCheckbox>
              </div>
              <div class="fld row-inline">
                <PonyCheckbox v-model="editForm.isPublic">发布到大厅</PonyCheckbox>
              </div>
              <div class="fld row-inline fld-last">
                <PonyCheckbox v-model="editForm.isWebVisible">网页公开</PonyCheckbox>
              </div>
            </section>
          </div>
          <footer class="modal-footer">
            <p v-if="editErr" class="err">{{ editErr }}</p>
            <div class="modal-actions">
              <button type="button" class="btn" :disabled="editSaving" @click="closeEdit">取消</button>
              <button type="button" class="btn btn-primary" :disabled="editSaving" @click="saveEdit">
                {{ editSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- 创建弹层（与「编辑」相同排版，归属 System） -->
    <Teleport to="body">
      <div
        v-if="createOpen"
        class="modal-mask admin-shell"
        role="dialog"
        aria-modal="true"
        @mousedown="onCreateBackdropMouseDown"
        @click.self="onCreateBackdropClickSelf"
      >
        <div class="modal card">
          <header class="modal-header">
            <div class="modal-header-left">
              <h3 class="modal-title">创建角色</h3>
              <p class="modal-id">拥有者将固定为 System</p>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="closeCreate">×</button>
          </header>
          <div class="modal-body modal-body-grid">
            <section class="form-panel">
              <h4 class="form-panel-title">基础信息</h4>
              <div class="fld fld-avatar">
                <span class="fld-avatar-label">头像</span>
                <div class="avatar-edit-row">
                  <div class="avatar-preview-box">
                    <img
                      v-if="createPreviewObjectUrl && !createAvatarFailed"
                      :src="createPreviewObjectUrl"
                      alt=""
                      class="avatar-preview-lg"
                      @error="createAvatarFailed = true"
                    />
                    <div v-else class="avatar-preview-ph-lg">{{ createPreviewLetter }}</div>
                  </div>
                  <div class="avatar-edit-actions">
                    <input
                      ref="createAvatarFileRef"
                      type="file"
                      accept="image/jpeg,image/png,image/webp,image/gif"
                      class="avatar-file-input"
                      @change="onCreateAvatarPick"
                    />
                    <button
                      type="button"
                      class="btn btn-sm btn-avatar-upload"
                      :disabled="createSaving"
                      @click="triggerCreateAvatarPick"
                    >
                      {{ createSaving ? '创建中…' : '选择本地图片' }}
                    </button>
                  </div>
                </div>
              </div>
              <label class="fld">
                <span>名称</span>
                <input v-model="createForm.name" type="text" placeholder="角色名称" />
              </label>
              <label class="fld">
                <span>角色 ID</span>
                <input v-model="createForm.id" class="mono" type="text" placeholder="留空自动生成 UUID" spellcheck="false" />
              </label>
              <label class="fld">
                <span>个性签名</span>
                <textarea v-model="createForm.signature" rows="3" placeholder="展示在角色主页上的短介绍" />
              </label>
              <label class="fld">
                <span>标签</span>
                <input v-model="createForm.tags" type="text" placeholder="用逗号分隔" />
              </label>
              <label class="fld fld-last">
                <span>角色设定</span>
                <textarea v-model="createForm.persona" rows="8" placeholder="角色提示词、背景、说话方式等" />
              </label>
            </section>

            <section class="form-panel">
              <h4 class="form-panel-title">角色档案</h4>
              <label class="fld">
                <span>种族</span>
                <input v-model="createForm.profileSpecies" type="text" placeholder="例如 飞马 / 人类 / 精灵" />
              </label>
              <label class="fld">
                <span>性别</span>
                <input v-model="createForm.profileGender" type="text" placeholder="例如 女性 / 雌性 / 男性" />
              </label>
              <label class="fld">
                <span>年龄</span>
                <input v-model="createForm.profileAge" type="text" placeholder="例如 22岁 / 成年 / 青少年" />
              </label>
              <label class="fld">
                <span>16人格</span>
                <div ref="createMbtiSelectRef" class="pony-select" :class="{ open: createMbtiMenuOpen }">
                  <button type="button" class="pony-select-trigger" @click.stop="createMbtiMenuOpen = !createMbtiMenuOpen">
                    <span>{{ mbtiLabel(createForm.profileMbti) }}</span>
                    <span class="pony-select-arrow">⌄</span>
                  </button>
                  <div v-if="createMbtiMenuOpen" class="pony-select-menu">
                    <button
                      type="button"
                      class="pony-select-option"
                      :class="{ selected: !createForm.profileMbti }"
                      @click="chooseCreateMbti('')"
                    >
                      <span class="pony-select-code">--</span>
                      <span class="pony-select-text">
                        <b>不展示</b>
                        <small>角色主页不显示 16 人格</small>
                      </span>
                      <span v-if="!createForm.profileMbti" class="pony-select-check">✓</span>
                    </button>
                    <button
                      v-for="item in mbtiOptions"
                      :key="item.code"
                      type="button"
                      class="pony-select-option"
                      :class="{ selected: createForm.profileMbti === item.code }"
                      @click="chooseCreateMbti(item.code)"
                    >
                      <span class="pony-select-code">{{ item.code }}</span>
                      <span class="pony-select-text">
                        <b>{{ item.name }}</b>
                        <small>{{ item.desc }}</small>
                      </span>
                      <span v-if="createForm.profileMbti === item.code" class="pony-select-check">✓</span>
                    </button>
                  </div>
                </div>
              </label>
              <label class="fld">
                <span>性格</span>
                <input v-model="createForm.profilePersonality" type="text" placeholder="例如 温柔、好奇、认真" />
              </label>
              <label class="fld">
                <span>兴趣</span>
                <input v-model="createForm.profileInterests" type="text" placeholder="例如 阅读、甜点、冒险" />
              </label>
              <label class="fld fld-last">
                <span>简介</span>
                <textarea v-model="createForm.profileIntro" rows="3" placeholder="公开角色简介，会作为角色档案的一部分带入角色设定" />
              </label>

              <h4 class="form-panel-title form-panel-title-spaced">角色主页素材</h4>
              <div class="fld">
                <span>封面</span>
                <div class="cover-grid">
                  <div v-if="createForm.profileCover" class="cover-item">
                    <img :src="avatarUrl(createForm.profileCover)" alt="" />
                    <button type="button" class="photo-remove" @click="removeCreateCover">×</button>
                  </div>
                  <button v-else type="button" class="cover-add" :disabled="profileImageUploading" @click="triggerCreateCoverPick">
                    +
                  </button>
                </div>
                <input
                  ref="createCoverFileRef"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  class="avatar-file-input"
                  @change="(e) => onProfileImagePick(e, 'createCover')"
                />
              </div>
              <div class="fld">
                <span>相册</span>
                <div class="photo-grid">
                  <div v-for="(photo, index) in createForm.profilePhotos" :key="`${photo}-${index}`" class="photo-item">
                    <img :src="avatarUrl(photo)" alt="" />
                    <button type="button" class="photo-remove" @click="removeCreatePhoto(index)">×</button>
                  </div>
                  <button type="button" class="photo-add" :disabled="profileImageUploading || createForm.profilePhotos.length >= 12" @click="triggerCreatePhotosPick">
                    +
                  </button>
                </div>
                <input
                  ref="createPhotosFileRef"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  class="avatar-file-input"
                  @change="(e) => onProfileImagePick(e, 'createPhotos')"
                />
              </div>

              <h4 class="form-panel-title form-panel-title-spaced">角色音色</h4>
              <div class="fld row-inline">
                <PonyCheckbox v-model="createForm.voiceEnabled">启用语音消息</PonyCheckbox>
              </div>
              <div class="fld">
                <span>音色来源</span>
                <div class="voice-source-tabs">
                  <button type="button" :class="{ active: createForm.voiceSourceMode === 'voice_id' }" @click="setVoiceSource(createForm, 'voice_id')">Voice ID</button>
                  <button type="button" :class="{ active: createForm.voiceSourceMode === 'instruct' }" @click="setVoiceSource(createForm, 'instruct')">描述</button>
                  <button type="button" :class="{ active: createForm.voiceSourceMode === 'clone' }" @click="setVoiceSource(createForm, 'clone')">参考音频</button>
                </div>
              </div>
              <label v-if="createForm.voiceSourceMode === 'voice_id'" class="fld">
                <span>Voice ID</span>
                <input v-model="createForm.voiceId" class="mono" type="text" placeholder="例如 qwen3tts:紫悦" spellcheck="false" />
              </label>
              <template v-else-if="createForm.voiceSourceMode === 'instruct'">
                <label class="fld">
                  <span>音色描述</span>
                  <textarea v-model="createForm.voiceInstruct" rows="3" placeholder="例如 清亮、轻快、靠近手机麦克风，语气自然" />
                </label>
                <div class="voice-action-row">
                  <button type="button" class="btn btn-sm" :disabled="voiceDesignBusy" @click="previewDesignVoice(createForm)">{{ voiceDesignBusy ? '生成中…' : '试听' }}</button>
                  <button type="button" class="btn btn-sm btn-primary" :disabled="voiceDesignBusy" @click="replaceDesignVoice(createForm)">{{ voiceDesignBusy ? '生成中…' : '更换' }}</button>
                </div>
              </template>
              <template v-else>
                <div class="fld row-inline">
                  <span>参考音频</span>
                  <button type="button" class="btn btn-sm btn-primary" :disabled="voiceReferenceUploading" @click="triggerVoiceAudioPick('create')">
                    {{ voiceReferenceUploading ? '上传中…' : '上传' }}
                  </button>
                  <small class="voice-file-name">{{ createForm.voiceReferenceAudioUrl ? createForm.voiceReferenceAudioUrl.split('/').pop() : '未上传' }}</small>
                </div>
                <input ref="createVoiceAudioFileRef" type="file" accept="audio/*" class="avatar-file-input" @change="(e) => onVoiceAudioPick(e, createForm)" />
                <label class="fld">
                  <span>音频文本</span>
                  <textarea v-model="createForm.voiceReferenceText" rows="3" placeholder="逐字填写参考音频中说出的内容" />
                </label>
                <label class="fld">
                  <span>附加指令</span>
                  <textarea v-model="createForm.voiceInstruct" rows="2" placeholder="可选：描述语速、情绪、距离感" />
                </label>
              </template>

              <h4 class="form-panel-title form-panel-title-spaced">发布状态</h4>
              <div class="fld row-inline">
                <PonyCheckbox v-model="createForm.isUserVisible">用户可见</PonyCheckbox>
              </div>
              <div class="fld row-inline">
                <PonyCheckbox v-model="createForm.isPublic">发布到大厅</PonyCheckbox>
              </div>
              <div class="fld row-inline fld-last">
                <PonyCheckbox v-model="createForm.isWebVisible">网页公开</PonyCheckbox>
              </div>
            </section>
          </div>
          <footer class="modal-footer">
            <p v-if="createErr" class="err">{{ createErr }}</p>
            <div class="modal-actions">
              <button type="button" class="btn" :disabled="createSaving" @click="closeCreate">取消</button>
              <button type="button" class="btn btn-primary" :disabled="createSaving" @click="saveCreate">
                {{ createSaving ? '创建中…' : '创建' }}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </Teleport>

    <AvatarCropModal
      v-model="cropOpen"
      :file="cropFile"
      @confirm="onAvatarCropped"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchAdminCharacters,
  editCharacter,
  deleteCharacter,
  deleteCharacterReference,
  uploadCharacterAvatar,
  uploadCharacterProfileImage,
  createCharacter,
  designCharacterVoice,
  uploadCharacterVoiceReferenceAudio,
} from '../../../api/admin'
import AvatarCropModal from '../../../components/admin/AvatarCropModal.vue'
import PonyCheckbox from '../../../components/PonyCheckbox.vue'
import { useAdminPagination } from '../../../composables/useAdminPagination'
import { useViewportPageSize } from '../../../composables/useViewportPageSize'
import { useAdminTableSort, cmpLocale, cmpNum, fmtDt } from '../../../composables/useAdminTableSort'
import { useColResize } from '../../../composables/useColResize'
import { useModalBackdropDismiss } from '../../../composables/useModalBackdropDismiss'
import { confirmAsync } from '../../../composables/useConfirm'
import { toast } from '../../../composables/useToast'
import AdminPager from '../../../components/admin/AdminPager.vue'
import '../../../styles/admin-shell.css'

const route = useRoute()
const router = useRouter()

const list    = ref([])
const error   = ref('')
const search  = ref('')
const avatarFailed = reactive({})
const visibilityFilter = ref('visible')

const listViewportRef = ref(null)
const { pageSize: viewportRows } = useViewportPageSize(listViewportRef, {
  rowHeight: 52,
  headHeight: 46,
  minRows: 4,
  maxRows: 200,
  slackPx: 20,
})

const { sortKey, sortDir, toggleSort, sortIcon } = useAdminTableSort('name', 'asc', (k) =>
  k === 'pub' ? 'desc' : 'asc',
)

const { startResize, gridVars } = useColResize(
  { name: 250, creator: 120, id: 300, visible: 108, bio: 340 },
  {
    min: 60,
    cssVarByKey: {
      name: '--cw-name',
      creator: '--cw-creator',
      id: '--cw-id',
      visible: '--cw-visible',
      bio: '--cw-bio',
    },
  },
)

function referencedSourceIdFromLocalId(c, sourceIds) {
  const id = String(c?.id || '')
  const sep = '__u_'
  if (!id.includes(sep)) return ''
  const sourceId = id.split(sep, 1)[0]
  return sourceId && sourceIds.has(sourceId) ? sourceId : ''
}

function sourceKeyFor(c, sourceIds) {
  if (c.isOfficialReference && c.officialSourceId) return c.officialSourceId
  if (c.isHallReference && c.hallSourceId) return c.hallSourceId
  if (c.isHallReference && c.sourceId) return c.sourceId
  const localSourceId = referencedSourceIdFromLocalId(c, sourceIds)
  if (localSourceId) return localSourceId
  return c.id
}

const groupedList = computed(() => {
  const groups = new Map()
  const sourceIds = new Set(list.value.map((c) => String(c.id || '')).filter(Boolean))
  for (const c of list.value) {
    const key = sourceKeyFor(c, sourceIds)
    if (!groups.has(key)) {
      groups.set(key, { source: null, refs: [] })
    }
    const group = groups.get(key)
    const isReference =
      (c.isOfficialReference && c.officialSourceId) ||
      (c.isHallReference && c.sourceId) ||
      !!referencedSourceIdFromLocalId(c, sourceIds)
    if (isReference) group.refs.push(c)
    else group.source = c
  }
  return Array.from(groups.entries()).map(([key, group]) => {
    const source = group.source || group.refs[0]
    const sourceOwner = String(source.owner || source.creator || '').trim().toLowerCase()
    const refs = group.refs
      .slice()
      .filter((ref) => {
        if (!group.source || !sourceOwner) return true
        const refOwner = String(ref.owner || ref.creator || '').trim().toLowerCase()
        return refOwner !== sourceOwner
      })
      .sort((a, b) => cmpLocale(a.owner || a.id, b.owner || b.id, 1))
    const sourceOwnerRow = group.source
      ? {
          ...group.source,
          owner: group.source.owner || group.source.creator || '',
          isSourceOwner: true,
        }
      : null
    const referenceRows = sourceOwnerRow ? [sourceOwnerRow, ...refs] : refs
    return {
      ...source,
      id: source.id || key,
      referenceRows,
      referenceCount: refs.length,
      referenceOwners: refs.map((r) => r.owner).filter(Boolean),
      isReferenceRepresentative: !group.source && refs.length > 0,
    }
  })
})

const referenceTotal = computed(() => list.value.filter((c) => c.isOfficialReference && c.officialSourceId).length)
const visibilityFilterLabel = computed(() => {
  if (visibilityFilter.value === 'hidden') return '用户不可见'
  if (visibilityFilter.value === 'all') return '全部'
  return '用户可见'
})
const visibilityFilterTitle = computed(() => `当前筛选：${visibilityFilterLabel.value}`)

function cycleVisibilityFilter() {
  visibilityFilter.value =
    visibilityFilter.value === 'visible'
      ? 'hidden'
      : visibilityFilter.value === 'hidden'
        ? 'all'
        : 'visible'
}

function characterSignature(c) {
  return String(c?.signature || c?.preview || c?.bio || c?.description || '')
}

function signaturePreview(c) {
  const text = characterSignature(c)
  return `${text.slice(0, 80)}${text.length > 80 ? '…' : ''}`
}

function isVoiceEnabled(c) {
  return c?.voiceEnabled === true || c?.voice_enabled === true
}

// 搜索过滤 + 排序
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let arr = groupedList.value.filter((c) => {
    if (visibilityFilter.value === 'visible' && !c.isUserVisible) return false
    if (visibilityFilter.value === 'hidden' && c.isUserVisible) return false
    if (!q) return true
    const tagStr = Array.isArray(c.tags) ? c.tags.join(' ') : String(c.tags || '')
    const refStr = (c.referenceRows || [])
      .map((r) => `${r.id || ''} ${r.owner || ''} ${r.creator || ''}`)
      .join(' ')
    return (
      (c.name || '').toLowerCase().includes(q) ||
      (c.id || '').toLowerCase().includes(q) ||
      (c.creator || '').toLowerCase().includes(q) ||
      (c.owner || '').toLowerCase().includes(q) ||
      refStr.toLowerCase().includes(q) ||
      characterSignature(c).toLowerCase().includes(q) ||
      tagStr.toLowerCase().includes(q)
    )
  })
  const dir = sortDir.value === 'asc' ? 1 : -1
  const sk = sortKey.value
  arr.sort((a, b) => {
    if (sk === 'name') return cmpLocale(a.name, b.name, dir)
    if (sk === 'creator') return cmpLocale(a.creator, b.creator, dir)
    if (sk === 'id') return cmpLocale(a.id, b.id, dir)
    if (sk === 'pub') return cmpNum(a.isPublic ? 1 : 0, b.isPublic ? 1 : 0, dir)
    if (sk === 'web') return cmpNum(a.isWebVisible ? 1 : 0, b.isWebVisible ? 1 : 0, dir)
    if (sk === 'voice') return cmpNum(isVoiceEnabled(a) ? 1 : 0, isVoiceEnabled(b) ? 1 : 0, dir)
    if (sk === 'bio') return cmpLocale(characterSignature(a), characterSignature(b), dir)
    return 0
  })
  return arr
})

const { page, totalPages, total, pagedItems, pageSize, next, prev, resetPage } =
  useAdminPagination(filtered, viewportRows)

watch([sortKey, sortDir, visibilityFilter], () => {
  resetPage()
})

const editOpen   = ref(false)
const editSaving = ref(false)
const editErr    = ref('')
const avatarFileRef = ref(null)
const avatarUploading = ref(false)
const editAvatarFailed = ref(false)
const editCoverFileRef = ref(null)
const editPhotosFileRef = ref(null)
const createCoverFileRef = ref(null)
const createPhotosFileRef = ref(null)
const editVoiceAudioFileRef = ref(null)
const createVoiceAudioFileRef = ref(null)
const profileImageUploading = ref(false)
const voiceReferenceUploading = ref(false)
const voiceDesignBusy = ref(false)
const VOICE_REFERENCE_MIN_SECONDS = 3
const VOICE_REFERENCE_MAX_SECONDS = 60
const VOICE_REFERENCE_MAX_BYTES = 25 * 1024 * 1024
const editMbtiMenuOpen = ref(false)
const createMbtiMenuOpen = ref(false)
const editVoicePolicyMenuOpen = ref(false)
const createVoicePolicyMenuOpen = ref(false)
const editMbtiSelectRef = ref(null)
const createMbtiSelectRef = ref(null)
const editVoicePolicySelectRef = ref(null)
const createVoicePolicySelectRef = ref(null)
const editForm = reactive({
  id: '',
  newId: '',
  name: '',
  signature: '',
  tags: '',
  persona: '',
  avatar: '',
  profileCover: '',
  profilePhotos: [],
  profileSpecies: '',
  profileGender: '',
  profileAge: '',
  profilePersonality: '',
  profileInterests: '',
  profileIntro: '',
  profileMbti: '',
  voiceEnabled: false,
  voiceId: '',
  voiceDecisionPolicy: 'director',
  voiceSourceMode: 'voice_id',
  voiceInstruct: '',
  voiceProfileId: '',
  voiceReferenceAudioUrl: '',
  voiceReferenceText: '',
  voiceCloneStatus: '',
  isUserVisible: true,
  isPublic: false,
  isWebVisible: false,
})
const editMeta = reactive({
  creator: '',
  createdAt: '',
  referenceCount: 0,
  referenceRows: [],
})

const createOpen   = ref(false)
const createSaving = ref(false)
const createErr    = ref('')
const createForm = reactive({
  id: '',
  name: '',
  signature: '',
  tags: '',
  persona: '',
  profileCover: '',
  profilePhotos: [],
  profileSpecies: '',
  profileGender: '',
  profileAge: '',
  profilePersonality: '',
  profileInterests: '',
  profileIntro: '',
  profileMbti: '',
  voiceEnabled: false,
  voiceId: '',
  voiceDecisionPolicy: 'director',
  voiceSourceMode: 'voice_id',
  voiceInstruct: '',
  voiceProfileId: '',
  voiceReferenceAudioUrl: '',
  voiceReferenceText: '',
  voiceCloneStatus: '',
  isUserVisible: true,
  isPublic: false,
  isWebVisible: false,
})
const createAvatarFileRef = ref(null)
const createPendingFile = ref(null)
const createPreviewObjectUrl = ref('')
const createAvatarFailed = ref(false)

const mbtiOptions = [
  { code: 'INTJ', name: '建筑师', desc: '冷静规划，擅长长期布局' },
  { code: 'INTP', name: '逻辑学家', desc: '好奇理性，喜欢拆解问题' },
  { code: 'ENTJ', name: '指挥官', desc: '目标明确，行动和掌控力强' },
  { code: 'ENTP', name: '辩论家', desc: '灵活机敏，享受新点子碰撞' },
  { code: 'INFJ', name: '提倡者', desc: '温柔坚定，重视深层意义' },
  { code: 'INFP', name: '调停者', desc: '理想主义，情感细腻真诚' },
  { code: 'ENFJ', name: '主人公', desc: '善于鼓舞，天然照顾他人' },
  { code: 'ENFP', name: '竞选者', desc: '热情自由，充满感染力' },
  { code: 'ISTJ', name: '物流师', desc: '可靠守序，重视责任和细节' },
  { code: 'ISFJ', name: '守卫者', desc: '体贴稳定，默默守护身边人' },
  { code: 'ESTJ', name: '总经理', desc: '务实果断，擅长组织执行' },
  { code: 'ESFJ', name: '执政官', desc: '亲切合群，重视关系和氛围' },
  { code: 'ISTP', name: '鉴赏家', desc: '冷静独立，擅长临场解决' },
  { code: 'ISFP', name: '探险家', desc: '柔和敏锐，追求真实体验' },
  { code: 'ESTP', name: '企业家', desc: '大胆直接，享受即时行动' },
  { code: 'ESFP', name: '表演者', desc: '活泼外放，喜欢带动气氛' },
]

const voicePolicyOptions = [
  { value: 'director', short: 'AI', label: '由导演决定', desc: '根据对话内容自动选择文本或语音' },
  { value: 'always_voice_when_available', short: 'ON', label: '可用时总是语音', desc: '语音服务可用时优先生成语音消息' },
  { value: 'off', short: 'OFF', label: '关闭', desc: '该角色不自动生成语音消息' },
]

function mbtiLabel(code) {
  const item = mbtiOptions.find((x) => x.code === code)
  return item ? `${item.code} · ${item.name}` : '不展示'
}

function voicePolicyLabel(value) {
  const item = voicePolicyOptions.find((x) => x.value === value)
  return item ? item.label : '由导演决定'
}

function chooseEditMbti(code) {
  editForm.profileMbti = code
  editMbtiMenuOpen.value = false
}

function chooseCreateMbti(code) {
  createForm.profileMbti = code
  createMbtiMenuOpen.value = false
}

function chooseEditVoicePolicy(value) {
  editForm.voiceDecisionPolicy = value
  editVoicePolicyMenuOpen.value = false
}

function chooseCreateVoicePolicy(value) {
  createForm.voiceDecisionPolicy = value
  createVoicePolicyMenuOpen.value = false
}

function setVoiceSource(form, mode) {
  form.voiceSourceMode = mode
  form.voiceDecisionPolicy = 'director'
}

function playAudioTransfer(transfer) {
  const base64 = transfer?.data_base64 || transfer?.dataBase64
  if (!base64) return false
  const mime = transfer.mime || 'audio/mpeg'
  const raw = atob(base64)
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }))
  const audio = new Audio(url)
  audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
  audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
  audio.play().catch(() => {})
  return true
}

async function requestDesignVoice(form, action) {
  const instruct = (form.voiceInstruct || '').trim()
  if (!instruct) {
    toast.error('请先输入描述')
    return
  }
  voiceDesignBusy.value = true
  try {
    const res = await designCharacterVoice({
      character_id: form.newId || form.id || '',
      character_name: form.name || '',
      voice_id: form.voiceProfileId || form.voiceId || '',
      instruct,
      action,
    })
    form.voiceSourceMode = 'instruct'
    form.voiceEnabled = true
    form.voiceProfileId = res.voiceProfileId || res.voice_profile_id || res.voiceId || res.voice_id || form.voiceProfileId
    form.voiceId = form.voiceProfileId
    form.voiceCloneStatus = res.designStatus || res.design_status || 'recipe_ready'
    playAudioTransfer(res.audioTransfer || res.audio_transfer)
    toast.success(action === 'replace' ? '音色已更换' : '正在试听')
  } catch (err) {
    toast.error(err.message || String(err))
  } finally {
    voiceDesignBusy.value = false
  }
}

function previewDesignVoice(form) {
  requestDesignVoice(form, 'preview')
}

function replaceDesignVoice(form) {
  requestDesignVoice(form, 'replace')
}

function triggerVoiceAudioPick(mode) {
  if (mode === 'edit') editVoiceAudioFileRef.value?.click()
  else createVoiceAudioFileRef.value?.click()
}

function formatVoiceDuration(seconds) {
  return seconds.toFixed(1).replace(/\.0$/, '')
}

function probeLocalAudioDuration(file) {
  return new Promise((resolve) => {
    if (!file || typeof Audio === 'undefined' || typeof URL === 'undefined') {
      resolve(null)
      return
    }
    const audio = new Audio()
    const url = URL.createObjectURL(file)
    const cleanup = () => {
      clearTimeout(timer)
      audio.removeAttribute('src')
      URL.revokeObjectURL(url)
    }
    const finish = (value) => {
      cleanup()
      resolve(value)
    }
    const timer = setTimeout(() => finish(null), 2500)
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      const duration = Number(audio.duration)
      finish(Number.isFinite(duration) && duration > 0 ? duration : null)
    }
    audio.onerror = () => finish(null)
    audio.src = url
  })
}

async function onVoiceAudioPick(e, form) {
  const input = e.target
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file) return
  const transcript = (form.voiceReferenceText || '').trim()
  if (!transcript) {
    toast.error('请先填写音频文本')
    return
  }
  if (file.size > VOICE_REFERENCE_MAX_BYTES) {
    toast.error('参考音频超过 25MB 限制')
    return
  }
  const localDuration = await probeLocalAudioDuration(file)
  if (localDuration !== null && localDuration < VOICE_REFERENCE_MIN_SECONDS) {
    toast.error(`参考音频不能短于 3 秒（当前约 ${formatVoiceDuration(localDuration)} 秒）`)
    return
  }
  if (localDuration !== null && localDuration > VOICE_REFERENCE_MAX_SECONDS) {
    toast.error(`参考音频不能超过 60 秒（当前约 ${formatVoiceDuration(localDuration)} 秒）`)
    return
  }
  voiceReferenceUploading.value = true
  try {
    const res = await uploadCharacterVoiceReferenceAudio({
      file,
      transcript,
      characterId: form.newId || form.id || '',
      voiceProfileId: form.voiceProfileId || '',
      voiceName: form.name || '',
    })
    form.voiceSourceMode = 'clone'
    form.voiceEnabled = true
    form.voiceReferenceAudioUrl = res.url || ''
    form.voiceReferenceText = res.transcript || transcript
    form.voiceProfileId = res.voiceProfileId || res.voice_profile_id || res.voiceId || res.voice_id || form.voiceProfileId
    form.voiceId = form.voiceProfileId
    form.voiceCloneStatus = res.cloneStatus || res.clone_status || 'recipe_ready'
    const cloneError = res.cloneError || res.clone_error || ''
    if (form.voiceCloneStatus === 'clone_failed') {
      toast.error(cloneError ? `参考音频已上传，但音色配方保存失败：${cloneError}` : '参考音频已上传，但音色配方保存失败')
    } else {
      toast.success('参考音频已上传，音色配方已保存')
    }
  } catch (err) {
    toast.error(err.message || String(err))
  } finally {
    voiceReferenceUploading.value = false
  }
}

function onDocumentPointerDown(event) {
  const target = event.target
  if (editMbtiMenuOpen.value && editMbtiSelectRef.value && !editMbtiSelectRef.value.contains(target)) {
    editMbtiMenuOpen.value = false
  }
  if (createMbtiMenuOpen.value && createMbtiSelectRef.value && !createMbtiSelectRef.value.contains(target)) {
    createMbtiMenuOpen.value = false
  }
  if (editVoicePolicyMenuOpen.value && editVoicePolicySelectRef.value && !editVoicePolicySelectRef.value.contains(target)) {
    editVoicePolicyMenuOpen.value = false
  }
  if (createVoicePolicyMenuOpen.value && createVoicePolicySelectRef.value && !createVoicePolicySelectRef.value.contains(target)) {
    createVoicePolicyMenuOpen.value = false
  }
}

/** 头像裁剪弹层：编辑 / 创建 共用 */
const cropOpen = ref(false)
const cropFile = ref(null)
const cropMode = ref('edit')

const createPreviewLetter = computed(() => {
  const n = (createForm.name || '').trim()
  return n ? n[0] : '?'
})

const avatarPreviewLetter = computed(() => {
  const n = (editForm.name || '').trim()
  return n ? n[0] : '?'
})

function avatarUrl(avatar) {
  if (!avatar || typeof avatar !== 'string') return ''
  const a = avatar.trim()
  if (a.startsWith('http') || a.startsWith('data:')) return a
  if (a.startsWith('/')) return a
  return `/${a.replace(/^\/+/, '')}`
}

function formatTagsForForm(tags) {
  if (!tags) return ''
  if (Array.isArray(tags)) return tags.filter(Boolean).join(', ')
  return String(tags)
}

function normalizeVoiceSource(value, character = {}) {
  const mode = String(value || '').trim().toLowerCase()
  if (['instruct', 'instruction', 'prompt'].includes(mode)) return 'instruct'
  if (['clone', 'reference', 'reference_audio'].includes(mode)) return 'clone'
  if (character.voiceReferenceAudioUrl || character.voice_reference_audio_url) return 'clone'
  if (character.voiceInstruct || character.voice_instruct) return 'instruct'
  return 'voice_id'
}

function fmtMetaTime(value) {
  return fmtDt(value)
}

function openEdit(c) {
  editErr.value = ''
  editAvatarFailed.value = false
  editMeta.creator = c.creator || ''
  editMeta.createdAt = c.created_at || c.createdAt || ''
  editMeta.referenceCount = Number(c.referenceCount || 0)
  editMeta.referenceRows = Array.isArray(c.referenceRows) ? c.referenceRows : []
  editForm.id = c.id || ''
  editForm.newId = c.id || ''
  editForm.name = c.name || ''
  editForm.signature = c.preview || c.signature || ''
  editForm.tags = formatTagsForForm(c.tags)
  editForm.persona = c.persona || c.prompt || ''
  editForm.avatar = c.avatar || ''
  editForm.profileCover = c.profileCover || ''
  editForm.profilePhotos = Array.isArray(c.profilePhotos) ? c.profilePhotos.filter(Boolean) : []
  editForm.profileSpecies = c.profileSpecies || ''
  editForm.profileGender = c.profileGender || ''
  editForm.profileAge = c.profileAge || ''
  editForm.profilePersonality = c.profilePersonality || ''
  editForm.profileInterests = c.profileInterests || ''
  editForm.profileIntro = c.profileIntro || c.bio || c.description || ''
  editForm.profileMbti = c.profileMbti || ''
  editForm.voiceEnabled = c.voiceEnabled === true || c.voice_enabled === true
  editForm.voiceId = c.voiceId || c.voice_id || c.id || ''
  editForm.voiceDecisionPolicy = c.voiceDecisionPolicy || c.voice_decision_policy || 'director'
  editForm.voiceSourceMode = normalizeVoiceSource(c.voiceSourceMode || c.voice_source_mode, c)
  editForm.voiceInstruct = c.voiceInstruct || c.voice_instruct || ''
  editForm.voiceProfileId = c.voiceProfileId || c.voice_profile_id || (String(editForm.voiceId).startsWith('ponyvoice:') ? editForm.voiceId : '')
  editForm.voiceReferenceAudioUrl = c.voiceReferenceAudioUrl || c.voice_reference_audio_url || ''
  editForm.voiceReferenceText = c.voiceReferenceText || c.voice_reference_text || ''
  editForm.voiceCloneStatus = c.voiceCloneStatus || c.voice_clone_status || ''
  editForm.isUserVisible = c.isUserVisible !== false
  editForm.isPublic = !!c.isPublic
  editForm.isWebVisible = !!c.isWebVisible
  editOpen.value = true
}

function triggerAvatarPick() {
  avatarFileRef.value?.click()
}

function onAvatarFileChange(e) {
  const input = e.target
  const file = input && input.files && input.files[0]
  if (input) input.value = ''
  if (!file || !editForm.id) return
  cropFile.value = file
  cropMode.value = 'edit'
  cropOpen.value = true
}

async function onAvatarCropped(file) {
  if (!file) return
  if (cropMode.value === 'edit') {
    if (!editForm.id) return
    avatarUploading.value = true
    editErr.value = ''
    try {
      const res = await uploadCharacterAvatar(editForm.id, file)
      if (res.avatar) {
        editForm.avatar = res.avatar
        editAvatarFailed.value = false
        avatarFailed[editForm.id] = false
        toast.success('头像已上传，请保存角色以生效')
      }
    } catch (err) {
      editErr.value = err.message || String(err)
      toast.error(editErr.value)
    } finally {
      avatarUploading.value = false
    }
  } else {
    revokeCreatePreview()
    createPendingFile.value = file
    createPreviewObjectUrl.value = URL.createObjectURL(file)
    createAvatarFailed.value = false
  }
  cropFile.value = null
}

function triggerEditCoverPick() {
  editCoverFileRef.value?.click()
}

function triggerEditPhotosPick() {
  editPhotosFileRef.value?.click()
}

function triggerCreateCoverPick() {
  createCoverFileRef.value?.click()
}

function triggerCreatePhotosPick() {
  createPhotosFileRef.value?.click()
}

function removeEditCover() {
  editForm.profileCover = ''
}

function removeCreateCover() {
  createForm.profileCover = ''
}

function removeEditPhoto(index) {
  editForm.profilePhotos = editForm.profilePhotos.filter((_, i) => i !== index)
}

function removeCreatePhoto(index) {
  createForm.profilePhotos = createForm.profilePhotos.filter((_, i) => i !== index)
}

async function uploadProfileImageFile(file) {
  if (!file) return ''
  const res = await uploadCharacterProfileImage(file)
  return res.url || ''
}

async function onProfileImagePick(e, target) {
  const input = e.target
  const files = Array.from((input && input.files) || [])
  if (input) input.value = ''
  if (!files.length) return
  profileImageUploading.value = true
  editErr.value = ''
  createErr.value = ''
  try {
    if (target === 'editCover') {
      editForm.profileCover = await uploadProfileImageFile(files[0])
    } else if (target === 'createCover') {
      createForm.profileCover = await uploadProfileImageFile(files[0])
    } else if (target === 'editPhotos') {
      const remain = Math.max(0, 12 - editForm.profilePhotos.length)
      const urls = []
      for (const file of files.slice(0, remain)) {
        const url = await uploadProfileImageFile(file)
        if (url) urls.push(url)
      }
      editForm.profilePhotos = [...editForm.profilePhotos, ...urls].slice(0, 12)
    } else if (target === 'createPhotos') {
      const remain = Math.max(0, 12 - createForm.profilePhotos.length)
      const urls = []
      for (const file of files.slice(0, remain)) {
        const url = await uploadProfileImageFile(file)
        if (url) urls.push(url)
      }
      createForm.profilePhotos = [...createForm.profilePhotos, ...urls].slice(0, 12)
    }
    toast.success('主页素材已上传，请保存角色以生效')
  } catch (err) {
    const msg = err.message || String(err)
    if (editOpen.value) editErr.value = msg
    if (createOpen.value) createErr.value = msg
    toast.error(msg)
  } finally {
    profileImageUploading.value = false
  }
}
function closeEdit() { editOpen.value = false }
const { onBackdropMouseDown, onBackdropClickSelf } = useModalBackdropDismiss(closeEdit)

function revokeCreatePreview() {
  if (createPreviewObjectUrl.value) {
    URL.revokeObjectURL(createPreviewObjectUrl.value)
    createPreviewObjectUrl.value = ''
  }
}

function openCreate() {
  createErr.value = ''
  revokeCreatePreview()
  createForm.name = ''
  createForm.id = ''
  createForm.signature = ''
  createForm.tags = ''
  createForm.persona = ''
  createForm.profileCover = ''
  createForm.profilePhotos = []
  createForm.profileSpecies = ''
  createForm.profileGender = ''
  createForm.profileAge = ''
  createForm.profilePersonality = ''
  createForm.profileInterests = ''
  createForm.profileIntro = ''
  createForm.profileMbti = ''
  createForm.voiceEnabled = false
  createForm.voiceId = ''
  createForm.voiceDecisionPolicy = 'director'
  createForm.voiceSourceMode = 'voice_id'
  createForm.voiceInstruct = ''
  createForm.voiceProfileId = ''
  createForm.voiceReferenceAudioUrl = ''
  createForm.voiceReferenceText = ''
  createForm.voiceCloneStatus = ''
  createForm.isUserVisible = true
  createForm.isPublic = false
  createForm.isWebVisible = false
  createPendingFile.value = null
  createAvatarFailed.value = false
  if (createAvatarFileRef.value) createAvatarFileRef.value.value = ''
  createOpen.value = true
}

function closeCreate() {
  revokeCreatePreview()
  createOpen.value = false
}

const { onBackdropMouseDown: onCreateBackdropMouseDown, onBackdropClickSelf: onCreateBackdropClickSelf } =
  useModalBackdropDismiss(closeCreate)

function triggerCreateAvatarPick() {
  createAvatarFileRef.value?.click()
}

function onCreateAvatarPick(e) {
  const input = e.target
  const file = input && input.files && input.files[0]
  if (input) input.value = ''
  revokeCreatePreview()
  createPendingFile.value = null
  createAvatarFailed.value = false
  if (!file) return
  cropFile.value = file
  cropMode.value = 'create'
  cropOpen.value = true
}

async function saveCreate() {
  const n = (createForm.name || '').trim()
  if (!n) {
    createErr.value = '请填写名称'
    return
  }
  createSaving.value = true
  createErr.value = ''
  try {
    const res = await createCharacter({
      id: (createForm.id || '').trim() || undefined,
      name: n,
      preview: createForm.signature,
      tags: createForm.tags,
      bio: createForm.profileIntro,
      profileIntro: createForm.profileIntro,
      persona: createForm.persona,
      profileCover: createForm.profileCover,
      profilePhotos: createForm.profilePhotos,
      profileSpecies: createForm.profileSpecies,
      profileGender: createForm.profileGender,
      profileAge: createForm.profileAge,
      profilePersonality: createForm.profilePersonality,
      profileInterests: createForm.profileInterests,
      profileMbti: createForm.profileMbti,
      voiceEnabled: createForm.voiceEnabled,
      voiceId: (createForm.voiceId || createForm.id || '').trim(),
      voiceDecisionPolicy: 'director',
      voiceSourceMode: createForm.voiceSourceMode,
      voiceInstruct: createForm.voiceInstruct,
      voiceProfileId: createForm.voiceProfileId,
      voiceReferenceAudioUrl: createForm.voiceReferenceAudioUrl,
      voiceReferenceText: createForm.voiceReferenceText,
      voiceCloneStatus: createForm.voiceCloneStatus,
      isUserVisible: createForm.isUserVisible,
      isPublic: createForm.isPublic,
      isWebVisible: createForm.isWebVisible,
    })
    const newId = res.character_id
    if (!newId) throw new Error('未返回 character_id')
    if (createPendingFile.value) {
      const up = await uploadCharacterAvatar(newId, createPendingFile.value)
      if (up.avatar) {
        await editCharacter({
          character_id: newId,
          new_character_id: newId,
          name: n,
          preview: createForm.signature,
          tags: createForm.tags,
          bio: createForm.profileIntro,
          profileIntro: createForm.profileIntro,
          persona: createForm.persona,
          avatar: up.avatar,
          profileCover: createForm.profileCover,
          profilePhotos: createForm.profilePhotos,
          profileSpecies: createForm.profileSpecies,
          profileGender: createForm.profileGender,
          profileAge: createForm.profileAge,
          profilePersonality: createForm.profilePersonality,
          profileInterests: createForm.profileInterests,
          profileMbti: createForm.profileMbti,
          voiceEnabled: createForm.voiceEnabled,
          voiceId: (createForm.voiceId || newId).trim(),
          voiceDecisionPolicy: 'director',
          voiceSourceMode: createForm.voiceSourceMode,
          voiceInstruct: createForm.voiceInstruct,
          voiceProfileId: createForm.voiceProfileId,
          voiceReferenceAudioUrl: createForm.voiceReferenceAudioUrl,
          voiceReferenceText: createForm.voiceReferenceText,
          voiceCloneStatus: createForm.voiceCloneStatus,
          isUserVisible: createForm.isUserVisible,
          isPublic: createForm.isPublic,
          isWebVisible: createForm.isWebVisible,
        })
      }
    }
    toast.success('已创建（归属 System）')
    closeCreate()
    await load()
  } catch (e) {
    const msg = e.message || String(e)
    createErr.value = msg
    toast.error(msg)
  } finally {
    createSaving.value = false
  }
}

async function saveEdit() {
  editSaving.value = true
  editErr.value    = ''
  try {
    await editCharacter({
      character_id: editForm.id,
      new_character_id: (editForm.newId || '').trim(),
      name: editForm.name,
      preview: editForm.signature,
      tags: editForm.tags,
      bio: editForm.profileIntro,
      profileIntro: editForm.profileIntro,
      persona: editForm.persona,
      avatar: editForm.avatar || undefined,
      profileCover: editForm.profileCover,
      profilePhotos: editForm.profilePhotos,
      profileSpecies: editForm.profileSpecies,
      profileGender: editForm.profileGender,
      profileAge: editForm.profileAge,
      profilePersonality: editForm.profilePersonality,
      profileInterests: editForm.profileInterests,
      profileMbti: editForm.profileMbti,
      voiceEnabled: editForm.voiceEnabled,
      voiceId: (editForm.voiceId || editForm.newId || editForm.id || '').trim(),
      voiceDecisionPolicy: 'director',
      voiceSourceMode: editForm.voiceSourceMode,
      voiceInstruct: editForm.voiceInstruct,
      voiceProfileId: editForm.voiceProfileId,
      voiceReferenceAudioUrl: editForm.voiceReferenceAudioUrl,
      voiceReferenceText: editForm.voiceReferenceText,
      voiceCloneStatus: editForm.voiceCloneStatus,
      isUserVisible: editForm.isUserVisible,
      isPublic: editForm.isPublic,
      isWebVisible: editForm.isWebVisible,
    })
    avatarFailed[editForm.id] = false
    toast.success('已保存')
    closeEdit()
    await load()
  } catch (e) {
    editErr.value = e.message || String(e)
    toast.error(editErr.value)
  } finally {
    editSaving.value = false
  }
}

async function onDelete(c) {
  if (
    !(await confirmAsync({
      title: '删除角色',
      message: `永久删除角色「${c.name || c.id}」？相关对话将级联删除，不可恢复。`,
      danger: true,
    }))
  )
    return
  try {
    await deleteCharacter(c.id, c.owner)
    toast.success('已删除')
    await load()
  } catch (e) {
    error.value = e.message || String(e)
    toast.error(error.value)
  }
}

async function cancelReference(refRow) {
  const sourceId = editForm.id
  const refId = refRow?.id || ''
  if (!sourceId || !refId) return
  const ok = await confirmAsync({
    title: '取消引用',
    message: `取消用户「${refRow.owner || '—'}」对「${editForm.name || sourceId}」的引用？该用户的引用入口会被移除。`,
    danger: true,
  })
  if (!ok) return
  try {
    await deleteCharacterReference(sourceId, refId)
    toast.success('引用已取消')
    await load()
    const refreshed = groupedList.value.find((c) => c.id === sourceId)
    if (refreshed) openEdit(refreshed)
  } catch (e) {
    const msg = e.message || String(e)
    editErr.value = msg
    toast.error(msg)
  }
}

async function toggleReferenceVisibility(refRow) {
  const refId = refRow?.id || ''
  if (!refId) return
  const nextVisible = refRow.isUserVisible === false
  try {
    await editCharacter({
      character_id: refId,
      new_character_id: refId,
      isUserVisible: nextVisible,
    })
    toast.success(nextVisible ? '已设为可见' : '已隐藏')
    await load()
    const refreshed = groupedList.value.find((c) => c.id === editForm.id)
    if (refreshed) openEdit(refreshed)
  } catch (e) {
    const msg = e.message || String(e)
    editErr.value = msg
    toast.error(msg)
  }
}

async function load() {
  error.value = ''
  try {
    list.value = await fetchAdminCharacters()
    resetPage()
    Object.keys(avatarFailed).forEach(k => delete avatarFailed[k])
  } catch (e) {
    error.value = e.message || String(e)
  }
}

function clearHighlightQuery() {
  const nq = { ...route.query }
  delete nq.highlight
  router.replace({ path: route.path, query: nq })
}

function applyHighlightFromRoute() {
  const raw = route.query.highlight
  if (raw == null || raw === '') return
  const id = decodeURIComponent(String(Array.isArray(raw) ? raw[0] : raw)).trim()
  if (!id) {
    clearHighlightQuery()
    return
  }
  if (!list.value.length) return
  const c = list.value.find((x) => (x.id || '') === id)
  if (c) {
    openEdit(c)
    search.value = (c.name || c.id || '').trim() || id
    clearHighlightQuery()
  } else {
    clearHighlightQuery()
  }
}

watch(
  () => [route.query.highlight, list.value],
  () => {
    applyHighlightFromRoute()
  },
  { flush: 'post' },
)

onMounted(() => {
  load()
  document.addEventListener('pointerdown', onDocumentPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<style scoped>
.section-root { min-height: 0; }

.card-fill {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.char-list-viewport {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── 工具栏 ── */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  margin-bottom: 0.75rem;
  gap: 0.5rem;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
/* 颜色与边框继承 .admin-shell input */
.search-input {
  width: 200px;
  max-width: 100%;
}

/* ── 列定义 ── */
.list-head,
.list-row {
  display: grid;
  grid-template-columns:
    36px /* av */
    var(--cw-name, 240px)
    var(--cw-creator, 110px)
    var(--cw-id, 300px)
    var(--cw-visible, 108px)
    44px /* pub */
    44px /* web */
    56px /* voice */
    var(--cw-bio, 340px)
    120px; /* act */
}

.visibility-filter-btn {
  appearance: none;
  border: 1px solid rgba(167, 139, 250, 0.45);
  background: rgba(99, 102, 241, 0.12);
  color: #c4b5fd;
  border-radius: 7px;
  padding: 0.22rem 0.48rem;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  line-height: 1.1;
  cursor: pointer;
  white-space: nowrap;
}
.visibility-filter-btn:hover {
  background: rgba(124, 58, 237, 0.2);
  border-color: rgba(196, 181, 253, 0.7);
}
.visibility-filter-btn--hidden {
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(239, 68, 68, 0.12);
  color: #fca5a5;
}
.visibility-filter-btn--all {
  border-color: rgba(148, 163, 184, 0.42);
  background: rgba(148, 163, 184, 0.1);
  color: #cbd5e1;
}

/* ── 表头 ── */
/* ── 列表体：分页填满视口；略超高时可纵向滚动，避免末行裁切 ── */
/* ── 行 ── */
/* ── 头像 ── */
.av {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  object-fit: cover;
  display: block;
}
.av.ph {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #334155;
  font-weight: 700;
  font-size: 0.8rem;
  border-radius: 6px;
  color: #cbd5e1;
}

/* ── 文字修饰 ── */
.fw     { font-weight: 600; font-size: 0.875rem; }
.col-name.fw {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}
.col-name.fw > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref-chip {
  flex-shrink: 0;
  padding: 0.1rem 0.38rem;
  border-radius: 999px;
  background: rgba(78, 191, 207, 0.14);
  color: #7dd3fc;
  font-size: 0.68rem;
  font-weight: 700;
}
.small  { font-size: 0.78rem; }
.mono   { font-family: 'Consolas', monospace; }
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 公开标记 ── */
.badge-on, .badge-off, .badge-web {
  display: inline-block;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
}
.badge-on  { background: rgba(61,168,130,0.14); color: #6fb894; }
.badge-off { background: rgba(100,116,139,0.15); color: #64748b; }
.badge-web { background: rgba(99,102,241,0.15); color: #818cf8; }

/* ── 操作按钮 ── */
.col-act {
  display: flex;
  gap: 0.3rem;
}

/* ── 编辑弹层（header / body / footer） ── */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 8000;
  background: rgba(15, 23, 42, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.modal {
  width: min(1040px, 100%);
  max-height: 90dvh;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  flex-shrink: 0;
}
.modal-header-left {
  min-width: 0;
}
.modal-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  line-height: 1.3;
}
.modal-id {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
  word-break: break-all;
}
.modal-close {
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  margin: -0.15rem -0.25rem 0 0;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--text-muted, #94a3b8);
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.modal-close:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text, #e2e8f0);
}
.modal-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1.25rem;
  -webkit-overflow-scrolling: touch;
}
.modal-body-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}
.form-panel {
  min-width: 0;
  padding: 1rem;
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.26);
}
.form-panel-title {
  margin: 0 0 0.9rem;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text, #e2e8f0);
}
.ownership-panel {
  margin: 0 0 1rem;
  padding: 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.18);
}
.ownership-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.55rem;
}
.ownership-grid span {
  display: block;
  margin-bottom: 0.18rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.7rem;
}
.ownership-grid strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
}
.reference-box {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
}
.reference-title {
  margin-bottom: 0.45rem;
  color: var(--text-muted, #94a3b8);
  font-size: 0.75rem;
  font-weight: 700;
}
.reference-list {
  display: grid;
  gap: 0.35rem;
  max-height: calc(4 * 2.25rem + 3 * 0.35rem);
  overflow-y: auto;
  overflow-x: hidden;
}
.reference-row {
  display: grid;
  grid-template-columns: minmax(70px, 0.8fr) minmax(0, 1.4fr) auto auto;
  align-items: center;
  gap: 0.45rem;
  min-height: 2.25rem;
  padding: 0.28rem 0.4rem;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.38);
}
.reference-owner,
.reference-id {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.74rem;
}
.reference-visibility-btn {
  border: 0;
  cursor: pointer;
  transition: transform 0.12s ease, filter 0.12s ease, box-shadow 0.12s ease;
}
.reference-visibility-btn:hover {
  filter: brightness(1.12);
  transform: translateY(-1px);
}
.reference-visibility-btn:focus-visible {
  outline: 2px solid rgba(196, 181, 253, 0.72);
  outline-offset: 2px;
}
.source-owner-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.35rem;
  padding: 0.16rem 0.34rem;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.18);
  color: #c4b5fd;
  font-size: 0.68rem;
  font-weight: 700;
  white-space: nowrap;
}
.btn-xs {
  padding: 0.16rem 0.34rem;
  font-size: 0.68rem;
}
.form-panel-title-spaced {
  margin-top: 1.15rem;
  padding-top: 1rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
}
.modal-footer {
  flex-shrink: 0;
  padding: 0.85rem 1.25rem;
  border-top: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}
.fld-last {
  margin-bottom: 0;
}
.fld span {
  color: #cbd5e1;
  font-weight: 500;
}
.fld input:not([type='checkbox']):not([type='radio']),
.fld textarea,
.fld select {
  width: 100%;
  box-sizing: border-box;
  padding: 0.55rem 0.75rem !important;
}
.fld select {
  border: 1px solid var(--input-border, rgba(148, 163, 184, 0.25));
  border-radius: var(--radius-sm, 6px);
  background: var(--input-bg, rgba(15, 23, 42, 0.72));
  color: var(--text, #e2e8f0);
}
.fld textarea {
  resize: vertical;
}
.row-inline {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}
.row-inline span {
  font-weight: 400;
  color: var(--text-muted, #94a3b8);
}
.err {
  color: #e8a0a0;
  font-size: 0.85rem;
  margin: 0 0 0.65rem;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

/* ── 编辑弹窗：头像（置顶、居中） ── */
.fld-avatar {
  align-items: center;
  text-align: center;
}
.fld-avatar-label {
  width: 100%;
  text-align: center;
}
.fld-avatar .avatar-edit-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.85rem;
  width: 100%;
}
.avatar-preview-box {
  flex-shrink: 0;
  width: 96px;
  height: 96px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.25));
  background: rgba(15, 23, 42, 0.6);
}
.avatar-preview-lg {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.avatar-preview-ph-lg {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  font-weight: 700;
  color: #94a3b8;
  background: #334155;
}
.avatar-edit-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  max-width: 320px;
}
.avatar-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}
/* 上传头像：描边强调，与主操作「保存」实心按钮区分 */
.btn-avatar-upload {
  background: transparent !important;
  border-color: rgba(159, 134, 214, 0.55) !important;
  color: var(--accent-mid, #bbb0ea) !important;
  font-weight: 600;
}
.btn-avatar-upload:hover:not(:disabled) {
  background: rgba(117, 73, 212, 0.12) !important;
  border-color: var(--accent-from, #9f86d6) !important;
  color: #ddd6f5 !important;
}
.btn-avatar-upload:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.cover-grid {
  display: grid;
  grid-template-columns: minmax(160px, 240px);
  gap: 0.55rem;
}
.cover-item,
.cover-add {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border-radius: 8px;
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  background: rgba(15, 23, 42, 0.6);
}
.cover-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-add {
  color: var(--accent-mid, #bbb0ea);
  font-size: 1.8rem;
  cursor: pointer;
}
.cover-add:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 0.55rem;
}
.photo-item,
.photo-add {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  border-radius: 8px;
  border: 1px solid var(--stroke, rgba(148, 163, 184, 0.18));
  background: rgba(15, 23, 42, 0.6);
}
.photo-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.photo-remove {
  position: absolute;
  top: 0.25rem;
  right: 0.25rem;
  width: 1.35rem;
  height: 1.35rem;
  border: none;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.78);
  color: #f8fafc;
  line-height: 1;
  cursor: pointer;
}
.photo-add {
  color: var(--accent-mid, #bbb0ea);
  font-size: 1.8rem;
  cursor: pointer;
}
.photo-add:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.pony-select {
  position: relative;
  z-index: 2;
}
.pony-select.open {
  z-index: 20;
}
.pony-select-trigger {
  width: 100%;
  min-height: 2.35rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid rgba(159, 134, 214, 0.34);
  border-radius: 9px;
  background:
    linear-gradient(180deg, rgba(30, 34, 54, 0.96), rgba(17, 21, 36, 0.96));
  color: var(--text, #e2e8f0);
  font: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.pony-select-trigger:hover {
  border-color: rgba(187, 176, 234, 0.58);
  background:
    linear-gradient(180deg, rgba(36, 39, 62, 0.98), rgba(19, 23, 40, 0.98));
}
.pony-select.open .pony-select-trigger {
  border-color: var(--accent-from, #9f86d6);
  box-shadow:
    0 0 0 3px rgba(117, 73, 212, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.pony-select-arrow {
  flex-shrink: 0;
  color: var(--accent-mid, #bbb0ea);
  font-size: 1rem;
  transition: transform 0.16s ease;
}
.pony-select.open .pony-select-arrow {
  transform: rotate(180deg);
}
.pony-select-menu {
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 0.45rem);
  max-height: 260px;
  overflow-y: auto;
  padding: 0.45rem;
  border: 1px solid rgba(159, 134, 214, 0.28);
  border-radius: 12px;
  background:
    linear-gradient(180deg, rgba(28, 30, 48, 0.98), rgba(17, 20, 34, 0.98));
  box-shadow:
    0 18px 48px rgba(0, 0, 0, 0.46),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.pony-select-option {
  width: 100%;
  display: grid;
  grid-template-columns: 3.4rem minmax(0, 1fr) 1.2rem;
  align-items: center;
  gap: 0.65rem;
  padding: 0.62rem 0.65rem;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text, #e2e8f0);
  text-align: left;
  cursor: pointer;
}
.pony-select-option:hover {
  background: rgba(117, 73, 212, 0.14);
}
.pony-select-option.selected {
  background: rgba(117, 73, 212, 0.22);
  color: #f5f3ff;
}
.pony-select-code {
  display: inline-flex;
  min-width: 3.1rem;
  height: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(159, 134, 214, 0.16);
  color: var(--accent-mid, #bbb0ea);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0.04em;
}
.pony-select-option.selected .pony-select-code {
  background: rgba(159, 134, 214, 0.28);
  color: #ede9fe;
}
.pony-select-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.pony-select-text b {
  font-size: 0.86rem;
  font-weight: 750;
}
.pony-select-text small {
  overflow: hidden;
  color: var(--text-muted, #94a3b8);
  font-size: 0.74rem;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pony-select-check {
  color: var(--accent-mid, #bbb0ea);
  font-size: 0.95rem;
  font-weight: 900;
}
.voice-source-tabs,
.voice-action-row {
  display: flex;
  gap: 0.6rem;
}
.voice-source-tabs button {
  flex: 1 1 0;
  min-height: 2.35rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.55);
  color: var(--text-muted, #94a3b8);
  font-weight: 800;
  cursor: pointer;
}
.voice-source-tabs button.active {
  border-color: var(--accent-from, #7549d4);
  background: rgba(117, 73, 212, 0.24);
  color: #e8e4ff;
}
.voice-action-row {
  padding: 0.15rem 0 0.85rem;
}
.voice-file-name {
  min-width: 0;
  color: var(--text-muted, #94a3b8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 820px) {
  .modal-body-grid {
    grid-template-columns: 1fr;
  }
}
</style>
