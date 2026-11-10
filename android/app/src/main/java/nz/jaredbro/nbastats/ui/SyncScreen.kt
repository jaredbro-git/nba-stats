package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.MacLink
import nz.jaredbro.nbastats.data.Store

/** Pairing with the Mac and copying its data. */
@Composable
fun SyncScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var message by remember { mutableStateOf<String?>(null) }
    var macs by remember { mutableStateOf<List<MacLink.Mac>?>(null) }
    var pairing by remember { mutableStateOf<MacLink.Mac?>(null) }
    var code by remember { mutableStateOf("") }
    val paired = MacLink.pairedMac(context)

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        message?.let { Banner(it) }
        if (paired != null && pairing == null) {
            Panel("Your Mac", note = "Paired with ${paired.second}. The phone copies its data when the app opens (every 30 minutes at most), " +
                "while NBA Stats is open on the Mac and both are on the same Wi-Fi. Scores update from stats.nba.com anywhere.") {
                val last = MacLink.lastCopy(context)
                Small(if (last == 0L) "Not copied yet." else "Last copied ${((System.currentTimeMillis() - last) / 60_000)} min ago.")
                Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button({ scope.launch { message = MacLink.sync(context) } }, enabled = !MacLink.busy) { Text("Copy now") }
                    OutlinedButton({ MacLink.unpair(context); message = "Unpaired. Your data stays on the phone." }) { Text("Unpair") }
                }
            }
        }
        if (paired == null || pairing != null) {
            Panel("Pair with your Mac", note = "Open NBA Stats on your Mac and go to its Phone page. Both need to be on the same Wi-Fi.") {
                if (pairing == null) {
                    Button({
                        scope.launch {
                            message = "Looking for your Mac…"
                            macs = MacLink.find(context)
                            message = if (macs!!.isEmpty()) "No Mac found. Check NBA Stats is open on it and you're on the same Wi-Fi." else null
                        }
                    }) { Text("Find my Mac") }
                    for (mac in macs.orEmpty()) {
                        OutlinedButton({
                            scope.launch {
                                try {
                                    withContext(Dispatchers.IO) { MacLink.askToPair(context, mac) }
                                    pairing = mac
                                    message = "Type the 6-digit code shown on your Mac's Phone page."
                                } catch (e: Exception) { message = e.message }
                            }
                        }, Modifier.fillMaxWidth().padding(top = 8.dp)) { Text("Pair with ${mac.name}") }
                    }
                } else {
                    OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, label = { Text("Code") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true, modifier = Modifier.fillMaxWidth())
                    Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button({
                            val mac = pairing!!
                            scope.launch {
                                try {
                                    withContext(Dispatchers.IO) { MacLink.confirm(context, mac, code) }
                                    pairing = null
                                    code = ""
                                    message = "Paired. Copying the data…"
                                    message = MacLink.sync(context)
                                } catch (e: Exception) { message = e.message }
                            }
                        }, enabled = code.length == 6) { Text("Pair") }
                        OutlinedButton({ pairing = null; code = "" }) { Text("Cancel") }
                    }
                }
            }
        }
        if (Store.exists(context)) {
            Store.loaded()?.let { lg -> Small("Data from the Mac: ${lg.players.size} players, ${lg.games.size} games, ${lg.cur} season.") }
        }
    }
}
