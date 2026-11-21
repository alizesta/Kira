package ai.kira.mobile.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun KiraPrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(onClick, modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.large) { Text(text) }
}
@Composable
fun KiraSecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(onClick, modifier.heightIn(min = 48.dp), enabled = enabled, shape = MaterialTheme.shapes.large) { Text(text) }
}
@Composable
fun KiraTextField(
    value: String, onValueChange: (String) -> Unit, label: String, modifier: Modifier = Modifier,
    placeholder: String? = null, singleLine: Boolean = true, enabled: Boolean = true, supportingText: String? = null
) {
    OutlinedTextField(
        value = value, onValueChange = onValueChange, modifier = modifier.fillMaxWidth(),
        label = { Text(label) }, placeholder = placeholder?.let { hint -> { Text(hint) } },
        supportingText = supportingText?.let { message -> { Text(message) } },
        singleLine = singleLine, enabled = enabled, shape = MaterialTheme.shapes.medium
    )
}
@Composable
fun KiraCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) { Column(Modifier.padding(16.dp), content = content) }
}
@Composable
fun KiraSectionHeader(title: String, actionLabel: String? = null, onAction: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onBackground)
        if (actionLabel != null && onAction != null) TextButton(onClick = onAction) { Text(actionLabel) }
    }
}
@Composable
fun KiraEmptyState(title: String, description: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Column(
        modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        Text(description, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        if (action != null) { Spacer(Modifier.height(16.dp)); action() }
    }
}
@Composable
fun KiraLoadingIndicator(modifier: Modifier = Modifier, label: String? = null) {
    Row(modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.primary)
        if (label != null) { Spacer(Modifier.width(12.dp)); Text(label, style = MaterialTheme.typography.bodyMedium) }
    }
}

/**
 * Horizontally browsable cards sized to leave a visible portion of the next card.
 * The preview is intentional: it communicates that more content is available.
 */
@Composable
fun <T> KiraPeekRow(
    items: List<T>,
    modifier: Modifier = Modifier,
    itemSpacing: androidx.compose.ui.unit.Dp = 12.dp,
    itemFraction: Float = 0.82f,
    itemContent: @Composable (T) -> Unit
) {
    require(itemFraction in 0.5f..0.95f) { "itemFraction must leave a useful next-card preview" }
    BoxWithConstraints(modifier.fillMaxWidth()) {
        val itemWidth = maxWidth * itemFraction
        androidx.compose.foundation.lazy.LazyRow(
            contentPadding = PaddingValues(end = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(itemSpacing)
        ) {
            items(items.size) { index ->
                Box(Modifier.width(itemWidth)) { itemContent(items[index]) }
            }
        }
    }
}

/** A compact connected sequence; completed/current/future states use semantics as well as colour. */
@Composable
fun KiraConnectedSteps(
    labels: List<String>,
    currentStep: Int,
    modifier: Modifier = Modifier
) {
    require(labels.isNotEmpty()) { "At least one step is required" }
    require(currentStep in labels.indices) { "currentStep must identify an existing step" }
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        labels.forEachIndexed { index, label ->
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                Surface(
                    color = when {
                        index < currentStep -> MaterialTheme.colorScheme.secondaryContainer
                        index == currentStep -> MaterialTheme.colorScheme.primaryContainer
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    },
                    shape = MaterialTheme.shapes.small
                ) {
                    Text(
                        if (index < currentStep) "✓" else (index + 1).toString(),
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        style = MaterialTheme.typography.labelMedium
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    label,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (index == currentStep) MaterialTheme.colorScheme.onBackground
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center
                )
            }
            if (index < labels.lastIndex) {
                HorizontalDivider(
                    modifier = Modifier.weight(0.45f).padding(bottom = 18.dp),
                    color = MaterialTheme.colorScheme.outlineVariant
                )
            }
        }
    }
}

/** Keeps secondary controls available without making the default task look complex. */
@Composable
fun KiraProgressiveDisclosure(
    label: String,
    modifier: Modifier = Modifier,
    initiallyExpanded: Boolean = false,
    content: @Composable ColumnScope.() -> Unit
) {
    var expanded by androidx.compose.runtime.remember(label) {
        androidx.compose.runtime.mutableStateOf(initiallyExpanded)
    }
    Column(modifier.fillMaxWidth()) {
        TextButton(
            onClick = { expanded = !expanded },
            modifier = Modifier.align(Alignment.Start)
        ) {
            Text(if (expanded) "−  $label" else "+  $label")
        }
        androidx.compose.animation.AnimatedVisibility(visible = expanded) {
            Column(content = content)
        }
    }
}
