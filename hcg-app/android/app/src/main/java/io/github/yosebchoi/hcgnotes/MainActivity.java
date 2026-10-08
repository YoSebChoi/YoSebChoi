package io.github.yosebchoi.hcgnotes;

import android.os.Bundle;
import android.view.WindowManager;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(ScreenPlugin.class);
        super.onCreate(savedInstanceState);
    }

    /** Keeps the screen on while the read timer runs (the page calls HcgScreen.keepOn / allowOff). */
    @CapacitorPlugin(name = "HcgScreen")
    public static class ScreenPlugin extends Plugin {
        @PluginMethod
        public void keepOn(PluginCall call) {
            getActivity().runOnUiThread(() -> getActivity().getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            call.resolve();
        }

        @PluginMethod
        public void allowOff(PluginCall call) {
            getActivity().runOnUiThread(() -> getActivity().getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            call.resolve();
        }
    }
}
