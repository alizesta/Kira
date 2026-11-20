package ai.kira.mobile

import ai.kira.mobile.application.provider.ProviderApplicationService
import ai.kira.mobile.domain.model.ProviderConnection
import ai.kira.mobile.domain.policy.FreeModelPolicy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import java.util.concurrent.Executors

@Composable
internal fun KiraRouteScreen(service: ProviderApplicationService) {
    val executor = remember { Executors.newSingleThreadExecutor() }
    val handler = remember { android.os.Handler(android.os.Looper.getMainLooper()) }
    val routes = remember { mutableStateListOf<ProviderConnection>() }
    val models = remember { mutableStateListOf<String>() }
    var providerId by remember { mutableStateOf("") }
    var apiKey by remember { mutableStateOf("") }
    var selectedModel by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("API Key را وارد کن؛ Provider و مدل رایگان خودکار تشخیص داده می‌شوند.") }

    DisposableEffect(executor) { onDispose { executor.shutdownNow() } }

    fun refreshRoutes() {
        routes.clear()
        routes.addAll(service.providers())
    }

    LaunchedEffect(service) {
        refreshRoutes()
        val selected = routes.firstOrNull { it.enabled } ?: routes.firstOrNull()
        if (selected != null) {
            providerId = selected.providerId
            selectedModel = selected.modelId
            models.addAll(service.availableModels(selected.providerId))
        }
    }

    Column(Modifier.fillMaxSize().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("اتصال API و مدل‌ها", style = MaterialTheme.typography.headlineSmall)
        OutlinedTextField(
            value = apiKey,
            onValueChange = { apiKey = it },
            label = { Text("API Key") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Button(
            onClick = {
                val key = apiKey.trim()
                if (busy || key.isBlank()) return@Button
                busy = true
                status = "در حال تشخیص Provider و دریافت مدل‌ها…"
                executor.execute {
                    try {
                        val result = service.connect(key)
                        handler.post {
                            apiKey = ""
                            providerId = result.provider.providerId
                            selectedModel = result.provider.modelId
                            models.clear()
                            models.addAll(result.availableModels)
                            refreshRoutes()
                            status = "اتصال برقرار شد؛ مدل رایگان انتخاب شد."
                            busy = false
                        }
                    } catch (error: Exception) {
                        handler.post { status = error.message ?: "اتصال ناموفق بود."; busy = false }
                    }
                }
            },
            enabled = !busy && apiKey.isNotBlank(),
            modifier = Modifier.fillMaxWidth()
        ) { Text("اتصال و انتخاب مدل رایگان") }

        Text("مدل فعال: " + selectedModel, style = MaterialTheme.typography.titleMedium)
        if (models.isNotEmpty()) {
            OutlinedButton(onClick = { expanded = true }, enabled = !busy) { Text("فهرست مدل‌های رایگان") }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                models.forEach { model ->
                    DropdownMenuItem(text = { Text(model) }, onClick = {
                        expanded = false
                        busy = true
                        executor.execute {
                            try {
                                val result = service.selectModel(providerId, model)
                                handler.post {
                                    selectedModel = result.provider.modelId
                                    models.clear()
                                    models.addAll(result.availableModels)
                                    refreshRoutes()
                                    status = "مدل ذخیره شد."
                                    busy = false
                                }
                            } catch (error: Exception) {
                                handler.post { status = error.message ?: "انتخاب مدل ناموفق بود."; busy = false }
                            }
                        }
                    })
                }
            }
            OutlinedButton(
                onClick = {
                    val recommended = FreeModelPolicy.recommendedModel(providerId, models.toList())
                    busy = true
                    executor.execute {
                        try {
                            val result = service.selectModel(providerId, recommended)
                            handler.post {
                                selectedModel = result.provider.modelId
                                refreshRoutes()
                                status = "مدل پیشنهادی انتخاب شد."
                                busy = false
                            }
                        } catch (error: Exception) {
                            handler.post { status = error.message ?: "انتخاب مدل ناموفق بود."; busy = false }
                        }
                    }
                },
                enabled = !busy
            ) { Text("انتخاب هوشمند") }
        }
        Text("ترتیب Routeها و Failover", style = MaterialTheme.typography.titleMedium)
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            itemsIndexed(routes, key = { _, route -> route.providerId }) { index, route ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(12.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(route.displayName, style = MaterialTheme.typography.titleMedium)
                            Text(route.modelId, style = MaterialTheme.typography.bodySmall)
                            Text("اولویت " + (index + 1), style = MaterialTheme.typography.labelSmall)
                        }
                        Switch(checked = route.enabled, enabled = !busy, onCheckedChange = { enabled ->
                            busy = true
                            executor.execute {
                                try {
                                    val updated = service.setEnabled(route.providerId, enabled)
                                    handler.post { routes.clear(); routes.addAll(updated); busy = false }
                                } catch (error: Exception) {
                                    handler.post { status = error.message ?: "تغییر Route ناموفق بود."; busy = false }
                                }
                            }
                        })
                    }
                }
            }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        Text(status, style = MaterialTheme.typography.bodySmall)
    }
}
