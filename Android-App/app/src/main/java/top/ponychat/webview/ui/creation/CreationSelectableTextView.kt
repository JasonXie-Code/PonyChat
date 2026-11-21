package top.ponychat.webview.ui.creation

import android.content.Context
import android.view.ActionMode
import android.view.Menu
import android.view.MenuItem
import android.widget.TextView

/** Ordinary block scrolling stays unfocused; explicit long press still allows text selection. */
internal class CreationSelectableTextView(context: Context) : TextView(context) {
    init {
        setTextIsSelectable(true)
        isFocusable = false; isFocusableInTouchMode = false
        customSelectionActionModeCallback = object : ActionMode.Callback {
            override fun onCreateActionMode(mode: ActionMode, menu: Menu) = true
            override fun onPrepareActionMode(mode: ActionMode, menu: Menu) = false
            override fun onActionItemClicked(mode: ActionMode, item: MenuItem) = false
            override fun onDestroyActionMode(mode: ActionMode) {
                clearFocus(); isFocusable = false; isFocusableInTouchMode = false
            }
        }
    }
    override fun performLongClick(): Boolean {
        isFocusable = true; isFocusableInTouchMode = true; requestFocus()
        return super.performLongClick()
    }
}
