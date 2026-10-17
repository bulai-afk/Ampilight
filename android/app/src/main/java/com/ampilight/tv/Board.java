package com.ampilight.tv;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Связь с ESP32 по UDP, как у приложения на Mac.
 * Цвета: байт 'D', затем RGB каждого диода. Поиск: "AMP?" → "AMP,<ip>,<число диодов>".
 */
public final class Board {
    public static final int PORT = 4210;

    public static final class Found {
        public final String ip;
        public final int leds;

        Found(String ip, int leds) {
            this.ip = ip;
            this.leds = leds;
        }
    }

    private Board() {}

    public static List<Found> discover(int timeoutMs) {
        List<Found> found = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        List<InetAddress> targets = broadcastTargets();
        byte[] ask = "AMP?".getBytes(StandardCharsets.US_ASCII);
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.setBroadcast(true);
            socket.setSoTimeout(300);
            long deadline = System.currentTimeMillis() + timeoutMs;
            long nextSend = 0;
            byte[] buf = new byte[256];
            while (System.currentTimeMillis() < deadline) {
                if (System.currentTimeMillis() >= nextSend) {
                    for (InetAddress target : targets) {
                        try {
                            socket.send(new DatagramPacket(ask, ask.length, target, PORT));
                        } catch (Exception ignored) {
                        }
                    }
                    nextSend = System.currentTimeMillis() + 400;
                }
                DatagramPacket reply = new DatagramPacket(buf, buf.length);
                try {
                    socket.receive(reply);
                } catch (SocketTimeoutException e) {
                    continue;
                }
                String text = new String(reply.getData(), 0, reply.getLength(), StandardCharsets.UTF_8).trim();
                if (!text.startsWith("AMP,")) continue;
                String ip = reply.getAddress().getHostAddress();
                if (!seen.add(ip)) continue;
                String[] parts = text.split(",");
                int leds = 0;
                if (parts.length >= 3) {
                    try {
                        leds = Integer.parseInt(parts[2].trim());
                    } catch (NumberFormatException ignored) {
                    }
                }
                found.add(new Found(ip, leds));
            }
        } catch (Exception ignored) {
        }
        return found;
    }

    private static List<InetAddress> broadcastTargets() {
        List<InetAddress> targets = new ArrayList<>();
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) continue;
                for (InterfaceAddress address : nif.getInterfaceAddresses()) {
                    InetAddress broadcast = address.getBroadcast();
                    if (broadcast != null && !targets.contains(broadcast)) targets.add(broadcast);
                }
            }
        } catch (Exception ignored) {
        }
        try {
            targets.add(InetAddress.getByName("255.255.255.255"));
        } catch (Exception ignored) {
        }
        return targets;
    }

    /** Ток одного канала WS2812 на полной яркости, мА. */
    private static final float CHANNEL_MA = 20f;
    /** Ток самой платы и «чёрных» диодов, мА. */
    private static final float IDLE_MA = 250f;

    /**
     * Пакет цветов для count диодов: диод i берёт цвет позиции i % colors.length.
     * Если кадр тянет больше maxMilliamps, весь кадр приглушается — иначе блок питания
     * проседает и ESP32 перезагружается или выпадает из Wi-Fi.
     */
    public static byte[] packet(int[] colors, int count, float brightness, int maxMilliamps) {
        byte[] data = new byte[1 + count * 3];
        data[0] = 'D';
        if (colors.length == 0) return data;
        long sum = 0;
        for (int i = 0; i < count; i++) {
            int c = colors[i % colors.length];
            sum += ((c >> 16) & 0xFF) + ((c >> 8) & 0xFF) + (c & 0xFF);
        }
        float milliamps = sum / 255f * CHANNEL_MA * brightness + IDLE_MA;
        float scale = brightness;
        if (maxMilliamps > 0 && milliamps > maxMilliamps) {
            scale *= Math.max(0f, maxMilliamps - IDLE_MA) / (milliamps - IDLE_MA);
        }
        for (int i = 0; i < count; i++) {
            int c = colors[i % colors.length];
            data[1 + i * 3] = (byte) Math.round(((c >> 16) & 0xFF) * scale);
            data[2 + i * 3] = (byte) Math.round(((c >> 8) & 0xFF) * scale);
            data[3 + i * 3] = (byte) Math.round((c & 0xFF) * scale);
        }
        return data;
    }

    /** Отвечает ли плата по адресу ip на запрос "AMP?". */
    public static boolean alive(String ip, int timeoutMs) {
        byte[] ask = "AMP?".getBytes(StandardCharsets.US_ASCII);
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.setSoTimeout(250);
            InetAddress address = InetAddress.getByName(ip);
            byte[] buf = new byte[256];
            long deadline = System.currentTimeMillis() + timeoutMs;
            while (System.currentTimeMillis() < deadline) {
                socket.send(new DatagramPacket(ask, ask.length, address, PORT));
                DatagramPacket reply = new DatagramPacket(buf, buf.length);
                try {
                    socket.receive(reply);
                } catch (SocketTimeoutException e) {
                    continue;
                }
                String text = new String(reply.getData(), 0, reply.getLength(), StandardCharsets.UTF_8);
                if (text.startsWith("AMP,")) return true;
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    public static byte[] black(int count) {
        byte[] data = new byte[1 + count * 3];
        data[0] = 'D';
        return data;
    }
}
