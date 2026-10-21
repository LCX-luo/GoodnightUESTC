package cn.lcx.goodnightuestc;

/** Approximate WGS84 to GCJ02, port of MIT coordtransform; see repository notices. */
public final class Coordinates {
    private Coordinates() {}
    public static double[] from(double lat,double lng,String system) {
        if (!Double.isFinite(lat)||!Double.isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180)
            throw new IllegalArgumentException("坐标无效");
        if("gcj02".equals(system)) return new double[]{lat,lng};
        if("wgs84".equals(system)) return gcj(lat,lng);
        throw new IllegalArgumentException("坐标系无效");
    }
    public static double[] gcj(double lat, double lng) {
        if (!Double.isFinite(lat) || !Double.isFinite(lng) || Math.abs(lat)>90 || Math.abs(lng)>180)
            throw new IllegalArgumentException("坐标无效");
        if (!(lng>73.66 && lng<135.05 && lat>3.86 && lat<53.55)) return new double[]{lat,lng};
        double x=lng-105, y=lat-35, pi=Math.PI;
        double a=-100+2*x+3*y+.2*y*y+.1*x*y+.2*Math.sqrt(Math.abs(x));
        a+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3;
        a+=(20*Math.sin(y*pi)+40*Math.sin(y/3*pi))*2/3;
        a+=(160*Math.sin(y/12*pi)+320*Math.sin(y*pi/30))*2/3;
        double b=300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x));
        b+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3;
        b+=(20*Math.sin(x*pi)+40*Math.sin(x/3*pi))*2/3;
        b+=(150*Math.sin(x/12*pi)+300*Math.sin(x/30*pi))*2/3;
        double r=Math.toRadians(lat), magic=1-.00669342162296594323*Math.pow(Math.sin(r),2), root=Math.sqrt(magic);
        return new double[]{lat+a*180/((6378245*(1-.00669342162296594323))/(magic*root)*pi),
            lng+b*180/(6378245/root*Math.cos(r)*pi)};
    }
    public static double distance(double lat1,double lng1,double lat2,double lng2) {
        double a=Math.pow(Math.sin(Math.toRadians(lat2-lat1)/2),2)
            +Math.cos(Math.toRadians(lat1))*Math.cos(Math.toRadians(lat2))*Math.pow(Math.sin(Math.toRadians(lng2-lng1)/2),2);
        return 2*6378137*Math.asin(Math.sqrt(Math.min(1,a)));
    }
}
