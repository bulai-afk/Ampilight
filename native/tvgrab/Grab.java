import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Process;
import android.os.SystemClock;
import java.io.BufferedOutputStream;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.Arrays;

/**
 * Снимки экрана ТВ без сжатия. Запуск через adb:
 *   CLASSPATH=/data/local/tmp/tvgrab.dex app_process / Grab <ширина> <высота> [кадров в секунду]
 * Каждый кадр: "AMPF", ширина и высота (по 2 байта, big-endian), затем RGBA построчно.
 * Метка нужна, потому что библиотеки ТВ иногда пишут свои строки в тот же stdout.
 */
public class Grab {
    public static void main(String[] args) throws Exception {
        int width = Integer.parseInt(args[0]);
        int height = Integer.parseInt(args[1]);
        int fps = args.length > 2 ? Integer.parseInt(args[2]) : 0;
        long frameMs = fps > 0 ? 1000L / fps : 0;
        int priority = args.length > 3 ? Integer.parseInt(args[3]) : 0;
        if (priority != 0) {
            try { Process.setThreadPriority(priority); } catch (Exception e) { System.err.println("prio " + e); }
        }

        Class<?> sc = Class.forName("android.view.SurfaceControl");
        Method shot = sc.getMethod("screenshot", Rect.class, int.class, int.class, int.class);
        Rect all = new Rect();
        // Буфер на один кадр: если Mac не успевает читать, write() ждёт, и новых снимков нет.
        OutputStream out = new BufferedOutputStream(new FileOutputStream(FileDescriptor.out),
                8 + width * height * 4);
        ByteBuffer pixels = ByteBuffer.allocate(width * height * 4);
        byte[] header = {'A', 'M', 'P', 'F',
                (byte) (width >> 8), (byte) width, (byte) (height >> 8), (byte) height};
        while (true) {
            long started = SystemClock.uptimeMillis();
            Bitmap frame = (Bitmap) shot.invoke(null, all, width, height, 0);
            pixels.clear();
            if (frame == null) {
                // Защищённое видео (Netflix и т.п.) система не отдаёт — шлём чёрный кадр.
                Arrays.fill(pixels.array(), (byte) 0);
                pixels.position(pixels.capacity());
            } else {
                Bitmap soft = frame.copy(Bitmap.Config.ARGB_8888, false);
                frame.recycle();
                soft.copyPixelsToBuffer(pixels);
                soft.recycle();
            }
            out.write(header);
            out.write(pixels.array(), 0, pixels.position());
            out.flush();
            long rest = Math.max(frame == null ? 150 : 0, frameMs - (SystemClock.uptimeMillis() - started));
            if (rest > 0) Thread.sleep(rest);
        }
    }
}
